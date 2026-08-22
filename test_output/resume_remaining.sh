#!/bin/bash
cd /Users/Zhuanz1/PycharmProjects/同花顺
export PYTHONPATH=/Users/Zhuanz1/PycharmProjects/同花顺
ALL_IDS="S-G04 S-G05 S-G06 S-G07 S-G08 T-01 T-02 T-03 T-04 T-05 T-06 T-07 T-08 T-09 T-10 T-11 T-12 E-01 E-02 E-04 E-05 E-06 E-07 E-08 E-09 E-10 E-11 E-12 E-21 E-22 E-23 E-24 E-25 E-26 E-27 E-28 E-31 E-39 E-41 E-42 E-43 E-44 E-45 E-46 E-47 E-48 E-49 E-50"
DONE_FILE=/Users/Zhuanz1/PycharmProjects/同花顺/test_output/done_ids.txt
touch "$DONE_FILE"
for id in T-01 T-02 T-03 T-04 T-05 T-06 T-07 T-08 T-09 T-10 S-G04 S-G05 S-G06 S-G07 S-G08; do echo $id >> "$DONE_FILE"; done
for attempt in 2 3 4 5 6 7 8; do
  REMAINING=""
  for id in $ALL_IDS; do
    if ! grep -qx "$id" "$DONE_FILE"; then REMAINING="$REMAINING $id"; fi
  done
  if [ -z "$(echo $REMAINING | tr -d ' ')" ]; then echo "ALL DONE"; break; fi
  echo "=== attempt $attempt, remaining:$REMAINING ==="
  ARGS=""
  for id in $REMAINING; do ARGS="$ARGS --case $id"; done
  python3 eval/surrogate_runner.py $ARGS > /Users/Zhuanz1/PycharmProjects/同花顺/test_output/surrogate_attempt_$attempt.log 2>&1
  EXIT=$?
  NEWEST=$(ls -td /Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_* | head -1)
  python3 -c "
import json
m = json.load(open('$NEWEST/run_manifest.json'))
with open('/Users/Zhuanz1/PycharmProjects/同花顺/test_output/done_ids.txt', 'a') as f:
    for cid in m.get('cases_completed') or []:
        f.write(cid + chr(10))
print('stop code:', (m.get('stop') or {}).get('code'))
"
  if [ $EXIT -eq 0 ]; then echo "clean exit"; break; fi
  echo "sleeping 30s before retry"
  sleep 30
done
echo FINAL_DONE_COUNT=$(sort -u /Users/Zhuanz1/PycharmProjects/同花顺/test_output/done_ids.txt | wc -l)
