"""Set the site's "Updated" date (SITE.updated in index.html) to today, US Eastern time."""
import re, sys
from datetime import datetime
from zoneinfo import ZoneInfo

path = sys.argv[1] if len(sys.argv) > 1 else "../index.html"
today = datetime.now(ZoneInfo("America/New_York"))
label = f"{today:%b} {today.day}, {today.year}"
s = open(path).read()
s, n = re.subn(r'(updated:\s*")[^"]*(")', rf"\g<1>{label}\g<2>", s, count=1)
if n != 1:
    sys.exit("Could not find SITE.updated in " + path)
open(path, "w").write(s)
print("Updated date set to", label)
