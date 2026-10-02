"""overture_raw.parquet から半径内の飲食系 POI を CSV に抜き出す。

  python scripts/extract_overture_food.py kameido

飲食の判定は taxonomy.hierarchy[1] = 'food_and_drink'。taxonomy が空でも
basic_category が restaurant/bar のものは含める（数件ある）。
"""
import sys

import duckdb

from common import RADIUS_M, STATIONS


def main(key):
    st = STATIONS[key]
    lat, lng = st["lat"], st["lng"]
    con = duckdb.connect()
    con.execute(f"""
    CREATE TABLE f AS
    SELECT *, 2*6371000*asin(sqrt(pow(sin(radians(lat-{lat})/2),2)
           + cos(radians({lat}))*cos(radians(lat))*pow(sin(radians(lng-{lng})/2),2))) dist_m
    FROM (SELECT *, (bbox.ymin+bbox.ymax)/2 lat, (bbox.xmin+bbox.xmax)/2 lng
          FROM 'data/{key}/overture_raw.parquet')""")
    out = f"data/{key}/overture_food.csv"
    con.execute(f"""
    COPY (
     SELECT id, names.primary AS name, taxonomy.primary AS category, taxonomy.hierarchy[2] AS cat_group,
            array_to_string(categories.alternate, '|') AS alternates, basic_category,
            brand.names.primary AS brand, round(lat,6) lat, round(lng,6) lng, round(dist_m) dist_m,
            round(confidence,3) confidence, addresses[1].freeform AS address,
            array_to_string(list_distinct([s.dataset FOR s IN sources]), '|') AS datasets,
            array_to_string(list_distinct([s.license FOR s IN sources IF s.license IS NOT NULL]), '|') AS licenses
     FROM f
     WHERE dist_m <= {RADIUS_M} AND (taxonomy.hierarchy[1] = 'food_and_drink'
           OR (taxonomy.hierarchy IS NULL AND basic_category IN ('restaurant','bar')))
     ORDER BY category, name
    ) TO '{out}' (HEADER)""")
    n = con.execute(f"SELECT count(*) FROM '{out}'").fetchone()[0]
    print(f"{n} rows -> {out}")


if __name__ == "__main__":
    main(sys.argv[1])
