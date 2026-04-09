#!/usr/bin/env python3
"""Live diagnostic: subscribe to the MQTT broker via MqttPacketProvider and show decoded packets.

Run with:  uv run python scripts/test_mqtt_live.py
Stop with: Ctrl-C

Prints one line per unique packet received, showing:
  observer_id | heard_at | snr | rssi | id | payload_type | src_hash
Cross-observer duplicates are counted but not re-displayed.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from meshcore_tools.config import get_mqtt_config, get_packet_source_type, get_region
from meshcore_tools.decoder import decode_packet
from meshcore_tools.providers.mqtt_provider import MqttPacketProvider


def main() -> None:
    source = get_packet_source_type()
    if source != "mqtt":
        print(f"WARNING: packet_source.type is '{source}', not 'mqtt' — using [mqtt] settings anyway")

    cfg = get_mqtt_config()
    region = get_region() or "LUX"

    print(f"Broker : {cfg['broker']}:{cfg['port']}")
    print(f"Topic  : {cfg['topic']}")
    print(f"Region : {region}")
    if "username" in cfg:
        print(f"Auth   : username={cfg['username']}")

    provider = MqttPacketProvider(region=region, **cfg)

    # Trigger connection
    print("\nConnecting...", flush=True)
    provider._ensure_connected()
    time.sleep(1.5)  # give the loop thread time to connect and subscribe
    print("Connected. Listening (Ctrl-C to stop)...\n")

    header = (f"{'observer':>24}  {'heard_at':>25}  {'snr':>6}  {'rssi':>5}  "
              f"{'id':>16}  {'type':>14}  src")
    print(header)
    print("-" * len(header))

    seen: set[str] = set()
    total = 0
    duplicates = 0
    start = time.time()

    try:
        while True:
            packets = provider.fetch_packets(region, limit=100)
            for p in packets:
                total += 1
                pkt_id = p["id"]
                if pkt_id in seen:
                    duplicates += 1
                    obs = (p.get("origin") or p.get("origin_id", ""))[:24]
                    print(f"  [DUP from {obs}] id={pkt_id}")
                    continue
                seen.add(pkt_id)

                dec = decode_packet(p.get("raw_data", "") or "")
                payload_type = dec.get("payload_type", "?")
                src_hash = (dec.get("decoded") or {}).get("src_hash", "")
                if payload_type == "Advert":
                    src_hash = ((dec.get("decoded") or {}).get("public_key", "") or "")[:12]

                obs = (p.get("origin") or p.get("origin_id", ""))[:24]
                heard = (p.get("heard_at") or "")[:25]
                snr = f"{p['snr']:.1f}" if p.get("snr") is not None else "-"
                rssi = str(p.get("rssi") or "-")

                print(f"{obs:>24}  {heard:>25}  {snr:>6}  {rssi:>5}  "
                      f"{pkt_id:>16}  {payload_type:>14}  {src_hash}")
                sys.stdout.flush()

            elapsed = time.time() - start
            sys.stderr.write(f"\r  [{elapsed:.0f}s] total={total} unique={len(seen)} dup={duplicates}  ")
            sys.stderr.flush()
            time.sleep(1)

    except KeyboardInterrupt:
        sys.stderr.write("\n")
        print(f"\nDone. {total} observations, {len(seen)} unique packets, "
              f"{duplicates} cross-observer duplicates in {time.time()-start:.0f}s")
        provider.disconnect()


if __name__ == "__main__":
    main()
