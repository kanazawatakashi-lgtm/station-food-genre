"""23区周辺の線路（Overture transportation の rail セグメント）を取得する。地図の背景用。

  python scripts/fetch_rail.py

出力: data/areas/tokyo23_rail.parquet（git 管理外）
出典: Overture Maps Foundation, Transportation（ODbL。元は OpenStreetMap）
"""
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from fetch_overture import RELEASE, s3fs

SEGMENTS = f"overturemaps-us-west-2/release/{RELEASE}/theme=transportation/type=segment"
BBOX = (139.54, 35.50, 139.94, 35.84)


def main():
    # 範囲に少しでもかかる線路を取る（範囲の端で線が切れないように）
    f = ((pc.field("subtype") == "rail") & (pc.field("bbox", "xmax") >= BBOX[0]) & (pc.field("bbox", "xmin") <= BBOX[2])
         & (pc.field("bbox", "ymax") >= BBOX[1]) & (pc.field("bbox", "ymin") <= BBOX[3]))
    t = ds.dataset(SEGMENTS, filesystem=s3fs(), format="parquet").to_table(
        columns=["id", "class", "names", "rail_flags", "level_rules", "geometry"], filter=f)
    pq.write_table(t, "data/areas/tokyo23_rail.parquet")
    print(f"{t.num_rows} 本 -> data/areas/tokyo23_rail.parquet")


if __name__ == "__main__":
    main()
