"""一括バックテスト: LOOSE-A/B/C を順番に実行してサマリ出力"""
import subprocess, sys, re

strategies = [
    "S_MAXHIT_14_EV_LOOSE_A",
    "S_MAXHIT_14_EV_LOOSE_B",
    "S_MAXHIT_14_EV_LOOSE_C",
]

for s in strategies:
    with open("hardcore_ev.py", encoding="utf-8") as f:
        code = f.read()
    code2 = re.sub(r'STRATEGY = "[^"]*"', f'STRATEGY = "{s}"', code, count=1)
    with open("hardcore_ev.py", "w", encoding="utf-8") as f:
        f.write(code2)
    ret = subprocess.run([sys.executable, "hardcore_ev.py"],
                         capture_output=True, text=True, encoding="utf-8")
    print(f"\n{'='*50}")
    for line in ret.stdout.splitlines():
        if any(k in line for k in ["バックテスト結果","的中率","ROI","対象レース","スキップ","総投資","総回収","全レース"]):
            print(line)
print("\n✅ 全3案 完了")
