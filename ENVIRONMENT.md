
## OSRM build (NQ-018)

- Source: infrastructure/osrm-data/map.osm.pbf (72.7 MB, BBBike extract)
- Car profile: extract 6.1 s, partition 12.8 s, customize ~3 s
- Peak RAM: 1.22 GB (extract), 1.12 GB (partition), 0.64 GB (customize)
- Graph: 8,249,479 raw nodes -> 2,707,241 used, 3,206,689 edge-expanded edges
- Boundary nodes: L1 149,006 / L2 25,745 / L3 4,292
- Algorithm: MLD (supports alternative routes, needed for NQ-052 rerouting)
- Verified: Indiranagar -> Cubbon Park = 6,433 m / 517 s
- Serving: osrm-car :5000, osrm-foot :5001, --max-table-size 100

## OSRM build (NQ-018)

- Source: infrastructure/osrm-data/map.osm.pbf (72.7 MB, BBBike extract)
- Car profile: extract 6.1 s, partition 12.8 s, customize ~3 s
- Peak RAM: 1.22 GB extract, 1.12 GB partition, 0.64 GB customize
- Graph: 8,249,479 raw nodes -> 2,707,241 used, 3,206,689 edge-expanded edges
- Boundary nodes: L1 149,006 / L2 25,745 / L3 4,292
- Algorithm: MLD (supports alternative routes, needed for NQ-052 rerouting)
- Verified: Indiranagar -> Cubbon Park = 6,433 m / 517 s
- Serving: osrm-car :5000, osrm-foot :5001, --max-table-size 100
