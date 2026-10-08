"""An in-memory GitHub repository for the publishing tests (Alan, Oct 11). Playwright routes https://api.github.com/**
here, so the page's real publishing code (repoRead / repoWrite / publishLive / saveHistory / publishInjOverrides) runs
against it and nothing ever reaches GitHub or the files on disk.

It answers the endpoints the site uses, the way GitHub does:
  GET   /repos/{repo}                       permissions.push = true
  GET   /user                               { login }
  GET   /repos/{repo}/git/ref/heads/main    the branch head
  GET   /repos/{repo}/git/commits/{sha}     { sha, tree: { sha }, parents, message }
  GET   /repos/{repo}/git/trees/{sha}       one level of entries
  GET   /repos/{repo}/git/blobs/{sha}       base64 in 60-character lines, with size
  POST  /repos/{repo}/git/blobs | trees | commits   (trees accept nested paths on a base_tree, like GitHub)
  PATCH /repos/{repo}/git/refs/heads/main   fast-forward only: 422 "Update is not a fast forward" otherwise
  GET   /repos/{repo}/compare/{sha}...main   status identical / ahead / diverged (is the commit on the branch?)
  GET   /repos/{repo}/contents/{path}       like GitHub: files over 1 MB come back with "content": "" and
                                            "encoding": "none" (the cause of the Oct 11 publishing failure)
Every request is logged in `calls`. `faults` injects failures: {"patch": status}, {"post_blob": status},
{"concurrent": fn(repo)} (runs once, just before the next PATCH), {"readback": True} (a new commit reads back wrong),
{"truncate": True} (blobs come back short).
Phase 1 additions: {"respond": fn(method, rest) -> None | "abort" | (status, body[, headers])} answers any request first
(network failures, 401/403/429, rate limits, tokens echoed in messages); {"patch_lost": True} moves the branch and then
drops the answer (the commit landed but the browser never heard); {"offline_after_patch": True} drops every request after
the next branch move, until cleared; {"bad_commit": True} returns a commit with no tree (an unexpected response shape).
`delay` = seconds to hold each request (a slow GitHub). `token_seen` records the Authorization headers.
"""
import base64, hashlib, itertools, json, re

ONE_MB = 1024 * 1024
_n = itertools.count(1)


class Repo:
    def __init__(self, files, repo="adequate-alan/myspam", branch="main", login="tester"):
        self.repo, self.branch, self.login = repo, branch, login
        self.blobs, self.trees, self.commits = {}, {}, {}
        self.calls, self.faults = [], {}
        self.delay, self.token_seen = 0, set()
        tree = self._tree_from({p: self._put_blob(b) for p, b in files.items()})
        self.head = self._commit(tree, [], "initial")
        self.initial = self.head

    # ---- object store -------------------------------------------------
    def _put_blob(self, data):
        sha = hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()
        self.blobs[sha] = data
        return sha

    def _put_tree(self, entries):   # entries: {name: ("blob" | "tree", sha)}
        body = json.dumps(sorted(entries.items())).encode()
        sha = hashlib.sha1(b"tree" + body).hexdigest()
        self.trees[sha] = dict(entries)
        return sha

    def _tree_from(self, flat):     # {"a/b.json": blob_sha} → root tree sha
        nested = {}
        for path, sha in flat.items():
            node, parts = nested, path.split("/")
            for p in parts[:-1]: node = node.setdefault(p, {})
            node[parts[-1]] = sha
        def build(node):
            return self._put_tree({k: ("tree", build(v)) if isinstance(v, dict) else ("blob", v) for k, v in node.items()})
        return build(nested)

    def _set_path(self, tree_sha, parts, blob_sha):
        entries = dict(self.trees[tree_sha]) if tree_sha else {}
        if len(parts) == 1: entries[parts[0]] = ("blob", blob_sha)
        else:
            sub = entries.get(parts[0]); sub_sha = sub[1] if sub and sub[0] == "tree" else None
            entries[parts[0]] = ("tree", self._set_path(sub_sha, parts[1:], blob_sha))
        return self._put_tree(entries)

    def _commit(self, tree, parents, message):
        sha = hashlib.sha1(f"commit {tree} {parents} {message} {next(_n)}".encode()).hexdigest()
        self.commits[sha] = {"tree": tree, "parents": list(parents), "message": message}
        return sha

    # ---- helpers for the tests ------------------------------------------
    def read(self, path, commit=None):
        tree = self.commits[commit or self.head]["tree"]
        for p in path.split("/"):
            e = self.trees[tree].get(p)
            if not e: return None
            if e[0] == "blob": return self.blobs[e[1]]
            tree = e[1]
        return None

    def commit_file(self, path, data, message="outside commit"):   # a commit made elsewhere (another browser, the weekly job)
        blob = self._put_blob(data)
        self.head = self._commit(self._set_path(self.commits[self.head]["tree"], path.split("/"), blob), [self.head], message)
        return self.head

    def log(self):
        out, sha = [], self.head
        while sha and sha != self.initial:
            c = self.commits[sha]; out.append(c["message"]); sha = c["parents"][0] if c["parents"] else None
        return out[::-1]

    # ---- the API ------------------------------------------------------
    def handle(self, route):
        req = route.request
        url, method = req.url.split("?")[0], req.method
        path = url.replace("https://api.github.com", "")
        self.calls.append((method, path))
        auth = req.headers.get("authorization")
        if auth: self.token_seen.add(auth)
        if self.delay:
            import time; time.sleep(self.delay)
        def send(status, body, headers=None):
            return route.fulfill(status=status, content_type="application/json", body=json.dumps(body), headers=headers or {})
        if self.faults.get("offline"): return route.abort()
        fn = self.faults.get("respond")
        if fn:
            r = fn(method, path.replace(f"/repos/{self.repo}", "", 1))
            if r == "abort": return route.abort()
            if r: return send(*r)
        R = f"/repos/{self.repo}"
        if path == R: return send(200, {"full_name": self.repo, "permissions": {"push": True}})
        if path == "/user": return send(200, {"login": self.login})
        if not path.startswith(R + "/"): return send(404, {"message": "Not Found"})
        rest = path[len(R):]
        if method == "GET" and rest == f"/git/ref/heads/{self.branch}":
            return send(200, {"ref": f"refs/heads/{self.branch}", "object": {"sha": self.head, "type": "commit"}})
        m = re.fullmatch(r"/git/commits/([0-9a-f]+)", rest)
        if method == "GET" and m:
            c = self.commits.get(m[1])
            if not c: return send(404, {"message": "Not Found"})
            if self.faults.get("bad_commit"): return send(200, {"sha": m[1], "parents": []})
            return send(200, {"sha": m[1], "tree": {"sha": c["tree"]}, "parents": [{"sha": s} for s in c["parents"]], "message": c["message"]})
        m = re.fullmatch(r"/git/trees/([0-9a-f]+)", rest)
        if method == "GET" and m:
            t = self.trees.get(m[1])
            if t is None: return send(404, {"message": "Not Found"})
            return send(200, {"sha": m[1], "truncated": False, "tree": [
                {"path": k, "mode": "040000" if typ == "tree" else "100644", "type": typ, "sha": s, **({"size": len(self.blobs[s])} if typ == "blob" else {})}
                for k, (typ, s) in sorted(t.items())]})
        m = re.fullmatch(r"/git/blobs/([0-9a-f]+)", rest)
        if method == "GET" and m:
            data = self.blobs.get(m[1])
            if data is None: return send(404, {"message": "Not Found"})
            shown = data[: len(data) // 2] if self.faults.get("truncate") else data
            b64 = base64.b64encode(shown).decode()
            return send(200, {"sha": m[1], "size": len(data), "encoding": "base64", "content": "\n".join(b64[i:i + 60] for i in range(0, len(b64), 60)) + "\n"})
        if method == "POST" and rest == "/git/blobs":
            if self.faults.get("post_blob"): return send(self.faults["post_blob"], {"message": "Server Error"})
            b = json.loads(req.post_data)
            data = base64.b64decode(b["content"]) if b.get("encoding") == "base64" else b["content"].encode()
            return send(201, {"sha": self._put_blob(data)})
        if method == "POST" and rest == "/git/trees":
            b = json.loads(req.post_data); tree = b.get("base_tree")
            for e in b["tree"]: tree = self._set_path(tree, e["path"].split("/"), e["sha"])
            return send(201, {"sha": tree})
        if method == "POST" and rest == "/git/commits":
            b = json.loads(req.post_data)
            sha = self._commit(b["tree"], b["parents"], b["message"])
            if self.faults.pop("readback", None):   # what GitHub stored isn't what was sent
                self.commits[sha]["tree"] = self.commits[b["parents"][0]]["tree"]
            return send(201, {"sha": sha})
        if method == "PATCH" and rest == f"/git/refs/heads/{self.branch}":
            fn = self.faults.pop("concurrent", None)
            if fn: fn(self)
            if self.faults.get("patch"): return send(self.faults["patch"], {"message": "Server Error"})
            b = json.loads(req.post_data); c = self.commits.get(b["sha"])
            if not c: return send(422, {"message": "Object does not exist"})
            if not b.get("force") and self.head not in c["parents"]: return send(422, {"message": "Update is not a fast forward"})
            self.head = b["sha"]
            if self.faults.pop("patch_lost", None): return route.abort()
            if self.faults.pop("offline_after_patch", None): self.faults["offline"] = True; return route.abort()
            return send(200, {"ref": f"refs/heads/{self.branch}", "object": {"sha": self.head}})
        m = re.fullmatch(r"/compare/([0-9a-f]+)\.\.\.(\w+)", rest)   # is base an ancestor of the branch? (status only)
        if method == "GET" and m:
            if m[1] not in self.commits: return send(404, {"message": "Not Found"})
            seen, todo = set(), [self.head]
            while todo:
                c = todo.pop()
                if c in seen: continue
                seen.add(c); todo += self.commits[c]["parents"]
            return send(200, {"status": "identical" if m[1] == self.head else "ahead" if m[1] in seen else "diverged"})
        m = re.fullmatch(r"/contents/(.+)", rest)
        if method == "GET" and m:
            data = self.read(m[1])
            if data is None: return send(404, {"message": "Not Found"})
            big = len(data) > ONE_MB
            return send(200, {"path": m[1], "size": len(data), "sha": "x", "encoding": "none" if big else "base64",
                              "content": "" if big else base64.b64encode(data).decode()})
        return send(404, {"message": "Not Found"})
