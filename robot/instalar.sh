#!/usr/bin/env bash
# Instala lo único que el robot necesita de fuera (robot/requisitos.txt, con versión y hash fijados) en un
# entorno aparte. Uso:  bash robot/instalar.sh <carpeta del entorno>
#
# PyPI a veces corta la conexión (p. ej. `BrokenPipeError`). Por eso pip reintenta cada descarga
# (--retries/--timeout) y, si aun así falla, todo se repite hasta 3 veces con una espera entre medias.
# Si falla las 3, el flujo de trabajo deja un aviso de «fallo temporal» (permisos.py --fallo-instalacion):
# no es un rechazo de la propuesta.
set -u

entorno="${1:?falta la carpeta del entorno}"
requisitos="$(dirname "$0")/requisitos.txt"
intentos=3
espera_base="${ROBOT_ESPERA_REINTENTO:-20}"  # segundos; las pruebas lo ponen a 0

python -m venv "$entorno" || exit 1
for intento in $(seq 1 "$intentos"); do
  if "$entorno/bin/pip" install --quiet --disable-pip-version-check --no-deps --only-binary :all: \
       --require-hashes --retries 5 --timeout 60 -r "$requisitos"; then
    exit 0
  fi
  if [ "$intento" -lt "$intentos" ]; then
    espera=$((intento * espera_base))
    echo "::warning::No se ha podido instalar BLAKE3 (intento $intento de $intentos). Se reintenta en ${espera} s."
    sleep "$espera"
  fi
done
echo "::error title=Fallo temporal de instalación (no es un rechazo)::No se ha podido instalar BLAKE3 desde PyPI tras $intentos intentos. Es un problema de red pasajero, no de la propuesta: hay que relanzar el robot."
exit 1
