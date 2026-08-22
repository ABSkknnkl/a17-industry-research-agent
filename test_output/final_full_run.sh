#!/bin/bash
cd /Users/Zhuanz1/PycharmProjects/同花顺
export PYTHONPATH=/Users/Zhuanz1/PycharmProjects/同花顺
DONE_FILE=/Users/Zhuanz1/PycharmProjects/同花顺/test_output/final_done_ids.txt
rm -f "$DONE_FILE"
touch "$DONE_FILE"
for attempt in $(seq 1 30); do
  REMAINING=""
  for id in E-01 E-02 E-03 E-04 E-05 E-06 E-07 E-08 E-09 E-10 E-11 E-12 E-13 E-14 E-15 E-16 E-17 E-18 E-19 E-20 E-21 E-22 E-23 E-24 E-25 E-26 E-27 E-28 E-29 E-30 E-31 E-32 E-33 E-34 E-35 E-36 E-37 E-38 E-39 E-40 E-41 E-42 E-43 E-44 E-45 E-46 E-47 E-48 E-49 E-50 I-C01 I-C02 I-C03 I-C04 I-C05 I-C06 I-C07 I-C08 I-C09 I-C10 I-C11 I-C12 I-C13 I-C14 I-C15 S-C01 S-C02 S-C03 S-C04 S-C05 S-C06 S-C07 S-C08 S-C09 S-C10 S-E01 S-E02 S-E03 S-E04 S-E05 S-E06 S-G01 S-G02 S-G03 S-G04 S-G05 S-G06 S-G07 S-G08 T-01 T-02 T-03 T-04 T-05 T-06 T-07 T-08 T-09 T-10 T-11 T-12; do
    if ! grep -qx "$id" "$DONE_FILE"; then REMAINING="$REMAINING $id"; fi
  done
  if [ -z "$(echo $REMAINING | tr -d ' ')" ]; then echo "ALL 101 DONE after attempt $attempt"; break; fi
  echo "=== attempt $attempt: $(echo $REMAINING | wc -w) remaining ===" >> /Users/Zhuanz1/PycharmProjects/同花顺/test_output/final_run_progress.log
  ARGS=""
  for id in $REMAINING; do ARGS="$ARGS --case $id"; done
  python3 eval/surrogate_runner.py $ARGS > /Users/Zhuanz1/PycharmProjects/同花顺/test_output/final_attempt_$attempt.log 2>&1
  NEWEST=$(ls -td /Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_* | head -1)
  python3 -c "
import json
m = json.load(open('$NEWEST/run_manifest.json'))
grades = {}
for line in open('$NEWEST/grades.jsonl'):
    g = json.loads(line)
    grades[g['case_id']] = g['verdict']
with open('/Users/Zhuanz1/PycharmProjects/同花顺/test_output/final_done_ids.txt', 'a') as f:
    for cid in m.get('cases_completed') or []:
        if grades.get(cid) not in (None, 'blocked'):
            f.write(cid + chr(10))
print('attempt stop:', (m.get('stop') or {}).get('code'), '| completed:', len(m.get('cases_completed') or []))
" >> /Users/Zhuanz1/PycharmProjects/同花顺/test_output/final_run_progress.log
  echo "cooling 150s" >> /Users/Zhuanz1/PycharmProjects/同花顺/test_output/final_run_progress.log
  sleep 150
done
echo FINAL_COUNT=$(sort -u "$DONE_FILE" | wc -l) >> /Users/Zhuanz1/PycharmProjects/同花顺/test_output/final_run_progress.log
