import json

with open("../data/upcoming_races.json", encoding="utf-8") as f:
    data = json.load(f)

for race in data["races"]:
    if race["race_num"] == 11:
        print(f"race_id={race['race_id']}, race_name={race.get('race_name')!r}, race_class={race.get('race_class')!r}")