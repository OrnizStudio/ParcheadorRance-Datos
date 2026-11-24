"""Fase D de los canales: la lista negra general y los nombres reservados (`docs/canales.md` §3).

Todo vive en `normas/` y solo lo cambia el Dueño del programa:

- `normas/lista-negra/usuarios/<xx>.json`: `{esquema, usuarios: [{id, cuenta, motivo, fecha, hasta?}]}`. Sus
  propuestas se rechazan y no pueden ser miembros de ningún canal.
- `normas/lista-negra/huellas/<xx>.json`: `{esquema, huellas: [{hash, motivo, fecha, tipo}]}` (`tipo`: `archivo` o
  `paquete`). Un paquete con ese hash no se acepta, ni una edición con ese hash en su huella.
- `normas/lista-negra/canales.json`: `{esquema, canales: [{id, esqueleto, motivo, fecha}]}`. El canal queda
  bloqueado: nadie salvo el Dueño toca su carpeta, y nadie crea un canal que se le parezca.
- `normas/nombres-reservados.json`: `{esquema, nombres: [texto…]}`. Nadie salvo el Dueño usa un @ o un nombre con
  ese esqueleto.

Los de usuarios y huellas van en 256 trozos: `<xx>` son los 2 primeros dígitos hex del SHA-256 de la clave (el id de
la cuenta en decimal, o el hash en minúsculas). El robot solo abre el trozo que necesita. Las reglas que valen también
para el Dueño (un trozo con una entrada que no es suya, vetar a un Dueño, vetar un canal verificado en `main`) están
en `comprobar_normas`.

Solo usa la biblioteca estándar.
"""

from __future__ import annotations

import datetime
import hashlib
import re

import canales

CARPETA = "normas/lista-negra/"
RUTA_USUARIOS = re.compile(r"normas/lista-negra/usuarios/([0-9a-f]{2})\.json")
RUTA_HUELLAS = re.compile(r"normas/lista-negra/huellas/([0-9a-f]{2})\.json")
RUTA_CANALES = "normas/lista-negra/canales.json"
RUTA_RESERVADOS = "normas/nombres-reservados.json"

TOPE_TROZO = 1024 * 1024
TOPE_CANALES = 5000
TOPE_RESERVADOS = 1000
LARGO_MOTIVO = 300
HASH = re.compile(r"(blake3|sha256):[0-9a-f]{64}")
TIPOS_HUELLA = ("archivo", "paquete")


def trozo(clave) -> str:
    """Los 2 primeros dígitos hex del SHA-256 de la clave (un id de cuenta se escribe en decimal)."""
    return hashlib.sha256(str(clave).strip().lower().encode("utf-8")).hexdigest()[:2]


def ruta_usuario(cuenta_id: int) -> str:
    return f"{CARPETA}usuarios/{trozo(cuenta_id)}.json"


def ruta_huella(huella: str) -> str:
    return f"{CARPETA}huellas/{trozo(huella)}.json"


def es_de_normas(ruta: str) -> bool:
    return ruta.startswith(CARPETA) or ruta == RUTA_RESERVADOS


# ───────────────────────────────────────── Lectura ─────────────────────────────────────────

def _objeto(datos, ruta):
    """El JSON estricto del archivo, o None si no existe. canales.JsonMalo si está mal."""
    if datos is None:
        return None
    return canales.leer_json_estricto(datos, ruta, TOPE_TROZO)


def _fecha_valida(valor) -> bool:
    try:
        return isinstance(valor, str) and len(valor) == 10 and datetime.date.fromisoformat(valor) is not None
    except ValueError:
        return False


def _filas(objeto, ruta, clave, campos, valida) -> tuple:
    """(filas buenas, errores) de la lista `clave` de un archivo de la lista negra."""
    if objeto is None:
        return [], []
    if not isinstance(objeto, dict):
        return [], [f"`{ruta}` tiene que ser un objeto `{{ … }}`."]
    errores = [f"`{ruta}`: el campo `{c}` no existe." for c in objeto if c not in ("esquema", clave)]
    if objeto.get("esquema") != 1:
        errores.append(f"`{ruta}`: falta `\"esquema\": 1`.")
    filas = objeto.get(clave, [])
    if not isinstance(filas, list):
        return [], errores + [f"`{ruta}`: `{clave}` tiene que ser una lista."]
    buenas = []
    for i, fila in enumerate(filas):
        donde = f"`{ruta}` › `{clave}` {i + 1}"
        if not isinstance(fila, dict):
            errores.append(f"{donde}: tiene que ser un objeto.")
            continue
        errores += [f"{donde}: el campo `{c}` no existe." for c in fila if c not in campos]
        problema = valida(fila) or canales.error_de_texto(fila.get("motivo"), LARGO_MOTIVO, 1)
        if problema:
            errores.append(f"{donde}: {problema}.")
            continue
        if not _fecha_valida(fila.get("fecha")):
            errores.append(f"{donde}: `fecha` tiene que ser aaaa-mm-dd.")
            continue
        buenas.append(fila)
    return buenas, errores


def _usuario_valido(fila):
    cid = fila.get("id")
    if not isinstance(cid, int) or isinstance(cid, bool) or not 0 < cid < 2 ** 53:
        return "`id` tiene que ser el número de la cuenta"
    if not isinstance(fila.get("cuenta"), str) or not 1 <= len(fila["cuenta"]) <= 39:
        return "`cuenta` tiene que ser el nombre de la cuenta"
    if "hasta" in fila and not _fecha_valida(fila["hasta"]):
        return "`hasta` tiene que ser aaaa-mm-dd"
    return None


def _huella_valida(fila):
    if not isinstance(fila.get("hash"), str) or not HASH.fullmatch(fila["hash"]):
        return "`hash` tiene que ser `blake3:` o `sha256:` y 64 dígitos hex en minúsculas"
    if fila.get("tipo") not in TIPOS_HUELLA:
        return "`tipo` tiene que ser `archivo` o `paquete`"
    return None


def _canal_valido(fila):
    if not isinstance(fila.get("id"), str) or not canales.ID_CANAL.match(fila["id"]):
        return "`id` tiene que ser el @ de un canal"
    if fila.get("esqueleto") != canales.esqueleto(fila["id"]):
        return f"`esqueleto` tiene que ser «{canales.esqueleto(fila['id'])}» (el del @)"
    return None


def leer_usuarios(datos, ruta):
    return _filas(_objeto(datos, ruta), ruta, "usuarios", ("id", "cuenta", "motivo", "fecha", "hasta"), _usuario_valido)


def leer_huellas(datos, ruta):
    return _filas(_objeto(datos, ruta), ruta, "huellas", ("hash", "motivo", "fecha", "tipo"), _huella_valida)


def leer_canales_vetados(datos, ruta=RUTA_CANALES):
    return _filas(_objeto(datos, ruta), ruta, "canales", ("id", "esqueleto", "motivo", "fecha"), _canal_valido)


def leer_reservados(datos, ruta=RUTA_RESERVADOS) -> tuple:
    """(nombres, errores)."""
    objeto = _objeto(datos, ruta)
    if objeto is None:
        return [], []
    if not isinstance(objeto, dict) or objeto.get("esquema") != 1 or set(objeto) - {"esquema", "nombres"} \
            or not isinstance(objeto.get("nombres"), list):
        return [], [f"`{ruta}` tiene que ser `{{\"esquema\": 1, \"nombres\": [ … ]}}`."]
    nombres = [n for n in objeto["nombres"] if isinstance(n, str) and canales.esqueleto(n)]
    errores = [] if len(nombres) == len(objeto["nombres"]) else [
        f"`{ruta}`: cada nombre tiene que ser un texto con alguna letra."]
    if len(nombres) > TOPE_RESERVADOS:
        errores.append(f"`{ruta}`: hay {len(nombres)} nombres y el máximo son {TOPE_RESERVADOS}.")
    return nombres, errores


# ───────────────────────────────────────── Consultas ─────────────────────────────────────────

class ListaIlegible(Exception):
    """Un archivo de la lista negra de `main` no se puede leer: mejor rechazar que dejar pasar a un vetado."""


def _leer_seguro(lector, datos, ruta):
    try:
        return lector(datos, ruta)[0]
    except canales.JsonMalo as error:
        raise ListaIlegible(f"`{ruta}` de `main` no se puede leer ({error}). Hasta que lo arregle el Dueño del "
                            "programa, el robot no acepta lo que dependa de él.") from error


def veto_de_cuenta(cuenta_id, leer_main, hoy: datetime.date | None = None):
    """El motivo por el que la cuenta está en la lista negra general (de `main`), o None. Un veto con `hasta` ya
    pasado no cuenta. `leer_main(ruta)` da los bytes de `main` o None."""
    if not isinstance(cuenta_id, int) or isinstance(cuenta_id, bool):
        return None
    hoy = hoy or datetime.datetime.now(datetime.timezone.utc).date()
    ruta = ruta_usuario(cuenta_id)
    for fila in _leer_seguro(leer_usuarios, leer_main(ruta), ruta):
        if fila["id"] == cuenta_id and not ("hasta" in fila and datetime.date.fromisoformat(fila["hasta"]) < hoy):
            return fila["motivo"]
    return None


def huella_vetada(huella, leer_main):
    """El motivo por el que ese hash está en la lista negra general de huellas, o None."""
    if not isinstance(huella, str):
        return None
    huella = huella.strip().lower()
    ruta = ruta_huella(huella)
    return next((f["motivo"] for f in _leer_seguro(leer_huellas, leer_main(ruta), ruta) if f["hash"] == huella), None)


def canales_vetados(leer_main) -> dict:
    """{@: motivo} de los canales bloqueados en `main`."""
    return {f["id"]: f["motivo"] for f in _leer_seguro(leer_canales_vetados, leer_main(RUTA_CANALES), RUTA_CANALES)}


def reservados(leer_main) -> list:
    """Los nombres reservados de `main`, más «Orniz» (siempre del Dueño)."""
    return list(canales.RESERVADOS) + _leer_seguro(leer_reservados, leer_main(RUTA_RESERVADOS), RUTA_RESERVADOS)


def distancia_uno(a: str, b: str) -> bool:
    """¿Se pasa de `a` a `b` cambiando, quitando o poniendo una sola letra?"""
    if a == b or abs(len(a) - len(b)) > 1:
        return a == b
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    corto, largo = (a, b) if len(a) < len(b) else (b, a)
    return any(largo[:i] + largo[i + 1:] == corto for i in range(len(largo)))


def parecido(texto: str, reservados_: list, existentes: dict, verificados: set):
    """Por qué un @ o un nombre de canal no vale por parecerse a otro, o None. `existentes` = {esqueleto: «@x (Nombre)»}
    de todos los canales (también retirados, bloqueados y @ anteriores); `verificados` = esqueletos de los verificados.
    """
    e = canales.esqueleto(texto)
    if not e:
        return None
    for r in reservados_:
        er = canales.esqueleto(r)
        if er and (er == e or (len(er) >= 4 and er in e)):
            return canales.PARECE_ORNIZ if r in canales.RESERVADOS else f"se parece a «{r}», que está reservado"
    if e in existentes:
        return f"se parece demasiado a {existentes[e]}"
    for otro in verificados:
        if distancia_uno(e, otro) and len(e) >= 4:
            return f"se parece demasiado a {existentes.get(otro, 'un canal verificado')}"
    return None


# ───────────────────────────────── Cambios en `normas/` (también el Dueño) ─────────────────────────────────

def comprobar_normas(cambios, leer, ids_duenos=frozenset(), verificados_main=frozenset()) -> list:
    """Motivos de rechazo de lo que la propuesta cambia en la lista negra general o en los nombres reservados. Solo el
    Dueño llega aquí (el resto de `normas/` ya se le rechaza a los demás), pero estas reglas valen también para él:
    la forma de cada archivo, cada entrada en su trozo, nunca vetar a un Dueño y nunca vetar un canal verificado en
    `main` (primero se le quita la verificación, en otra propuesta). `cambios` son (ruta, estado) y `leer(ruta, lado)`
    da los bytes de `main` (`antes`) o tras la propuesta (`despues`)."""
    motivos = []
    for ruta, estado in cambios:
        if estado == "D" or not es_de_normas(ruta):
            continue
        datos = leer(ruta, "despues")
        if datos is not None and len(datos) > TOPE_TROZO:
            motivos.append(f"`{ruta}` pesa {len(datos) // 1024} KB y el máximo es 1 MB: no cabe en un trozo.")
            continue
        try:
            if m := RUTA_USUARIOS.fullmatch(ruta):
                filas, errores = leer_usuarios(datos, ruta)
                motivos += errores
                for f in filas:
                    if trozo(f["id"]) != m[1]:
                        motivos.append(f"`{ruta}`: la cuenta {f['id']} va en `usuarios/{trozo(f['id'])}.json`.")
                    if f["id"] in ids_duenos:
                        motivos.append(f"`{ruta}`: {f['cuenta']} es Dueño del programa y no se puede vetar.")
            elif m := RUTA_HUELLAS.fullmatch(ruta):
                filas, errores = leer_huellas(datos, ruta)
                motivos += errores
                motivos += [f"`{ruta}`: `{f['hash'][:20]}…` va en `huellas/{trozo(f['hash'])}.json`."
                            for f in filas if trozo(f["hash"]) != m[1]]
            elif ruta == RUTA_CANALES:
                filas, errores = leer_canales_vetados(datos, ruta)
                motivos += errores
                if len(filas) > TOPE_CANALES:
                    motivos.append(f"`{ruta}`: hay {len(filas)} canales y el máximo son {TOPE_CANALES}.")
                try:
                    antes = {f["id"] for f in _leer_seguro(leer_canales_vetados, leer(ruta, "antes"), ruta)}
                except ListaIlegible:
                    antes = set()  # el Dueño arregla un archivo roto de `main`
                for f in filas:
                    if f["id"] not in antes and f["id"] in verificados_main:
                        motivos.append(f"`{ruta}`: @{f['id']} está verificado: quítale antes la verificación.")
            elif ruta == RUTA_RESERVADOS:
                motivos += leer_reservados(datos, ruta)[1]
            else:
                motivos.append(f"`{ruta}`: en `normas/lista-negra/` solo van `usuarios/<xx>.json`, "
                               "`huellas/<xx>.json` y `canales.json`.")
        except canales.JsonMalo as error:
            motivos.append(str(error))
    return motivos
