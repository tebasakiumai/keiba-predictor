import json

with open("../data/upcoming_races.json", encoding="utf-8") as f:
    data = json.load(f)

print(f"レース数: {len(data['races'])}")
print()
print(json.dumps(data["races"][0], ensure_ascii=False, indent=2))