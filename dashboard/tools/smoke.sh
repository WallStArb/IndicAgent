#!/bin/bash
# usage: tools/smoke.sh PORT ; checks server-rendered text and the 404 on a running build
P=$1
B=http://localhost:$P
fail=0
check() { # path, expected text
  if curl -s "$B$1" | grep -q "$2"; then echo "ok   $1"; else echo "FAIL $1 missing: $2"; fail=1; fi
}
check / "Agentic quantitative research platform"
check / "How the agents work"
check / "is being built and is not running"
check /pipeline "Pipeline"
check /data "Data"
check /instruments "Instruments"
check /concepts "Concepts"
check /research "Research"
check /books "forward runner not built"
check /system "System"
check /instruments/AAPL "AAPL"
code=$(curl -s -o /dev/null -w "%{http_code}" "$B/nope")
if [ "$code" = "404" ]; then echo "ok   /nope 404"; else echo "FAIL /nope returned $code"; fail=1; fi
for bad in "—" "ensemble" "swarm"; do
  if curl -s "$B/" | grep -qi "$bad"; then echo "FAIL / contains $bad"; fail=1; fi
done
exit $fail
