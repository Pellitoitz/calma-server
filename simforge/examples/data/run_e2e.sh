#!/usr/bin/env bash
# END-TO-END: measured data -> import -> validate -> analyse -> fit -> engineer decision -> apply -> approve -> run.
# Uses SYNTHETIC TEST DATA (examples/data/synthetic/tiempos_montaje.xlsx). Fully offline, no LLM. Reproducible:
# fixed data file, deterministic fit ids, sequential decision ids, fixed simulation seeds.
#
#   bash examples/data/run_e2e.sh            (workspace in a temporary directory)
set -euo pipefail
cd "$(dirname "$0")/../.."
export SIMFORGE_WORKSPACE="${SIMFORGE_WORKSPACE:-$(mktemp -d)}"
X=examples/data/synthetic/tiempos_montaje.xlsx
sf() { echo; echo "\$ simforge $*"; python -m simforge.cli "$@"; }

sf project new "E2E montaje" --model examples/data/e2e_selective_per_circuit.yaml
P=e2e_montaje
sf project approve $P --by ingeniera_ana --note "modelo base revisado"
sf project run $P --reps 5                                     # baseline: 30 s/circuito ASSUMED
sf data preview $X                                             # which sheets?
sf data preview $X --sheet Hoja1                               # which columns? (Tiempo: no unit in the header)
sf data import $P $X --name montaje --sheet Hoja1 --column Tiempo --unit s --timestamp Fecha \
   --quantity PROCESSING_TIME --basis PER_CIRCUIT --synthetic --by ingeniera_ana \
   --description "estudio de tiempos montaje manual (sintético)"
sf data inspect $P montaje@v1                                  # DATA PROFILE: 1 missing, 2 outlier candidates
sf data rows $P montaje@v1 KEEP 20 61 --reason "ciclos largos reales: caída de tornillo anotada en el parte" \
   --by ingeniera_ana --method "IQR/MAD"
sf data fit $P montaje@v1 --by ingeniera_ana                   # ranking + plausibility + SUGGESTED candidate
FIT=$(python -m simforge.cli data inspect $P montaje@v1 --json | python -c "import json,sys; print(json.load(sys.stdin)['fit']['fit_id'])")
sf data decide $P montaje@v1 USE_FITTED --fit "$FIT" --candidate lognormal --by ingeniera_ana \
   --reason "menor AIC; P99.9 (~76 s) coherente con los atascos observados (95 s)"
sf data apply $P montaje@v1 dec_001 --target nodes.assembly.params.process_time --target-basis PER_CIRCUIT \
   --by ingeniera_ana --ack WORK_UNITS_SCALING
echo; echo "# the new version is NOT approved: running is refused until the engineer approves it"
python -m simforge.cli project run $P || true
sf project approve $P --by ingeniera_ana --note "tiempo de montaje desde datos montaje@v1 (lognormal)"
sf project run $P --reps 5
sf project versions $P
sf data trace $P nodes.assembly.params.process_time
sf data inspect $P montaje@v1 | tail -1
echo; echo "workspace: $SIMFORGE_WORKSPACE"
