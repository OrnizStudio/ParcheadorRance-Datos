"""Trabajo `publicar` (fase B de los canales, `docs/canales.md` §1.5, §1.6 y §1.7).

Tras cada fusión en `main` (y a mano, o cuando el Dueño sube algo directamente):

1. **Regenera `catalogo/catalogo.json`** (esquema 1, el que leen las ≤0.2.x) juntando los archivos sueltos de `main`
   (`particion.juntar`), con `versionCatalogo` + 1, si lo que dice ha cambiado. Lo hace con una propuesta propia
   (rama `robot/catalogo`) que se aprueba y se fusiona sola: su contenido sale entero de `main`, así que no hay nada
   que juzgar. Como las propuestas que abre GitHub Actions no lanzan flujos de trabajo, el propio trabajo deja la
   comprobación `permisos` en verde en ese commit antes de fusionarla.
2. **Escribe la rama `publicado`**: `indice.json` y el índice por juego de Programa › Juegos originales,
   `programa/juegos/<xx>.json` (256 trozos por el SHA-256 del id). Es un único commit sin padres que sustituye al
   anterior (la rama no crece). Si nada ha cambiado, no escribe.

Antes de la migración (sin archivos sueltos en `main`) no regenera nada: el índice sale de partir el `catalogo.json`
de `main` en memoria.

No ejecuta nada de ninguna propuesta: solo lee `main` con git. Solo usa la biblioteca estándar.
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import json
import os
import subprocess
import sys

import lector_app
import particion
import permisos
import sueltos

RAMA_PUBLICADO = "publicado"
RAMA_CATALOGO = "robot/catalogo"
TOPE_ARCHIVO = 8 * 1024 * 1024  # ningún archivo publicado pasa de aquí (el tope del parcheador al descargar)
COMPROBACION = "permisos"       # la comprobación obligatoria de `main`
INTENTOS = 3


class ErrorPublicar(RuntimeError):
    """No se puede publicar sin dejar algo mal: se para y se dice por qué (el `main` sigue como estaba)."""


# ───────────────────────────────────────── El catálogo de las ≤0.2.x ─────────────────────────────────────────

def catalogo_regenerado(archivos: dict, catalogo_main: bytes | None):
    """Los bytes del `catalogo.json` nuevo, o None si el de `main` ya dice lo mismo (sin contar la versión).

    ErrorPublicar si los archivos no se pueden juntar, si el resultado no lo puede leer la app o si la versión de
    `main` no deja subir una más (eso lo arregla el Dueño a mano)."""
    try:
        actual = lector_app.leer(catalogo_main) if catalogo_main is not None else None
    except lector_app.JsonIlegible:
        actual = None
    version = actual.get("versionCatalogo") if isinstance(actual, dict) else None
    if not (isinstance(version, int) and not isinstance(version, bool) and 0 <= version < lector_app.VERSION_MAXIMA):
        raise ErrorPublicar(f"`{permisos.RUTA_CATALOGO}` de `main` no tiene una `versionCatalogo` válida ({version!r}): "
                            "lo tiene que arreglar el Dueño del programa a mano.")
    try:
        nuevo = particion.juntar(archivos, version + 1)
    except particion.ErrorParticion as error:
        raise ErrorPublicar(f"Los archivos del catálogo de `main` no se pueden juntar: {error}") from None
    if isinstance(actual, dict) and particion.mismo_catalogo(dict(actual, versionCatalogo=0), dict(nuevo, versionCatalogo=0)):
        return None
    errores = lector_app.errores_de_la_app(nuevo)
    if errores:
        raise ErrorPublicar("El catálogo juntado no lo podría leer el parcheador: " + "; ".join(errores[:5]))
    datos = permisos.canales.escribir_como_la_app(nuevo).encode("utf-8")
    if len(datos) > TOPE_ARCHIVO:
        raise ErrorPublicar(f"El catálogo juntado pesa {len(datos) / 1048576:.1f} MB y el máximo son 8 MB.")
    return datos


# ───────────────────────────────────────── La rama `publicado` ─────────────────────────────────────────

def trozo(juego_id: str) -> str:
    return hashlib.sha256(juego_id.encode("utf-8")).hexdigest()[:2]


def _json(valor) -> bytes:
    try:
        return (json.dumps(valor, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    except UnicodeEncodeError:
        # Un texto con un sustituto suelto (no debería llegar: lector_app los rechaza): mejor escapado que parado.
        return (json.dumps(valor, ensure_ascii=True, separators=(",", ":")) + "\n").encode("ascii")


def _objeto(datos):
    try:
        objeto = lector_app.leer(datos)
    except lector_app.JsonIlegible:
        return None
    return objeto if isinstance(objeto, dict) else None


def _fecha(valor):
    return valor if isinstance(valor, str) and len(valor) <= 40 else None


def indice_por_juego(archivos: dict) -> dict:
    """{id: entrada} del índice de Programa › Juegos originales (§1.7), con todos los canales. Lo que no se puede
    leer no entra (el robot ya rechaza que llegue a `main`; esto no debe caerse si llega)."""
    juegos, ediciones, parches = {}, {}, {}
    for ruta, datos in archivos.items():
        tipo = sueltos.tipo_de_ruta(ruta)
        if tipo is None:
            continue
        objeto = _objeto(datos)
        if objeto is None:
            continue
        if tipo[0] == "juego":
            juegos[tipo[1]] = objeto
        elif tipo[0] == "edicion":
            ediciones.setdefault(tipo[1], {})[tipo[2]] = objeto
        else:
            parches.setdefault(tipo[2], {})[tipo[1]] = objeto
    indice = {}
    for jid, central in sorted(juegos.items()):
        alta = central.get("alta") if isinstance(central.get("alta"), dict) else None
        lista = central.get("ediciones") if isinstance(central.get("ediciones"), list) else []
        eds = []
        relacion = {}
        if alta and isinstance(alta.get("canal"), str):
            relacion.setdefault(alta["canal"], set()).add("alta")
        for eid in lista:
            ed = ediciones.get(jid, {}).get(eid) if isinstance(eid, str) else None
            if ed is None:
                continue
            tiendas = ed.get("tiendas") if isinstance(ed.get("tiendas"), list) else []
            tienda = next((t.get("nombre") for t in tiendas if isinstance(t, dict) and isinstance(t.get("nombre"), str)), None)
            ed_alta = ed.get("alta") if isinstance(ed.get("alta"), dict) else None
            if ed_alta and isinstance(ed_alta.get("canal"), str):
                relacion.setdefault(ed_alta["canal"], set()).add("edicion")
            eds.append({"id": eid, "nombre": ed.get("nombre") if isinstance(ed.get("nombre"), str) else None,
                        "tienda": tienda, "alta": ed_alta})
        resumen_parches, total_versiones, ultima_total = [], 0, None
        for canal, parche in sorted(parches.get(jid, {}).items()):
            relacion.setdefault(canal, set()).add("parche")
            versiones, publicas, retiradas, ultima = 0, 0, 0, None
            for ed in parche.get("ediciones") or []:
                if not isinstance(ed, dict):
                    continue
                for v in ed.get("versiones") or []:
                    if not isinstance(v, dict):
                        continue
                    versiones += 1
                    estado = v.get("estado")
                    publicas += estado in ("publico", "anterior")
                    retiradas += estado == "retirada"
                    fecha = _fecha(v.get("fecha"))
                    if fecha and (ultima is None or fecha > ultima["fecha"]):
                        ultima = {"version": v.get("version") if isinstance(v.get("version"), str) else None,
                                  "fecha": fecha, "edicion": ed.get("id")}
            antiguo = parche.get("parche")
            if versiones == 0 and isinstance(antiguo, dict) and isinstance(antiguo.get("version"), str):
                # Parche de los de antes de las versiones (un solo bloque `parche`): la app lo cuenta como una
                # versión publicada, y el índice igual, para que la fila y el detalle digan lo mismo.
                versiones, publicas = 1, 1
                fecha = _fecha(antiguo.get("fecha"))
                ultima = {"version": antiguo["version"], "fecha": fecha, "edicion": None} if fecha else None
            total_versiones += versiones
            if ultima and (ultima_total is None or ultima["fecha"] > ultima_total):
                ultima_total = ultima["fecha"]
            resumen_parches.append({"canal": canal, "estado": parche.get("estado") if isinstance(parche.get("estado"), str) else None,
                                    "versiones": versiones, "publicas": publicas, "retiradas": retiradas,
                                    "ultima": ultima})
        orden = {"alta": 0, "edicion": 1, "parche": 2}
        indice[jid] = {
            "id": jid,
            "titulo": central.get("titulo") if isinstance(central.get("titulo"), str) else None,
            "estado": central.get("estado", "activo") if isinstance(central.get("estado", "activo"), str) else None,
            "alta": alta,
            "ediciones": eds,
            "parches": resumen_parches,
            "totales": {"canales": len(resumen_parches), "versiones": total_versiones, "ultima": ultima_total},
            "relacionados": [{"canal": c, "como": sorted(como, key=orden.get)} for c, como in sorted(relacion.items())],
        }
    return indice


def archivos_publicados(archivos: dict, catalogo: dict | None, main_sha: str, ahora: str) -> dict:
    """{ruta: bytes} de la rama `publicado`: `indice.json` y `programa/juegos/<xx>.json`."""
    por_trozo = {}
    for jid, entrada in indice_por_juego(archivos).items():
        por_trozo.setdefault(trozo(jid), []).append(entrada)
    resultado = {f"programa/juegos/{t}.json": _json({"esquema": 1, "juegos": entradas})
                 for t, entradas in sorted(por_trozo.items())}
    for ruta, datos in resultado.items():
        if len(datos) > TOPE_ARCHIVO:
            raise ErrorPublicar(f"`{ruta}` pesa {len(datos) / 1048576:.1f} MB y el máximo son 8 MB.")
    programa = _objeto(archivos.get(particion.RUTA_PARCHEADOR, b"")) or {}
    launcher = programa.get("launcher", (catalogo or {}).get("launcher"))
    resultado["indice.json"] = _json({
        "esquema": 1, "generado": ahora, "main": main_sha,
        "versionCatalogo": (catalogo or {}).get("versionCatalogo"),
        "launcher": launcher,
        "trozos": {ruta: "sha256:" + hashlib.sha256(datos).hexdigest() for ruta, datos in sorted(resultado.items())},
    })
    return resultado


def _sin_fecha(indice: bytes) -> bytes:
    """El índice sin lo que cambia en cada publicación (para saber si hay algo nuevo que publicar)."""
    objeto = _objeto(indice) or {}
    objeto.pop("generado", None)
    objeto.pop("main", None)
    return _json(objeto)


# ───────────────────────────────────────── git y GitHub ─────────────────────────────────────────

def _git(*argumentos, entrada: bytes | None = None, entorno=None) -> bytes:
    return subprocess.run(["git", *argumentos], input=entrada, capture_output=True, check=True,
                          env=entorno).stdout


def _entorno_con_token(token: str | None):
    """Para `git push` y `git fetch` contra GitHub sin dejar el token en la línea de órdenes ni en `.git/config`."""
    entorno = dict(os.environ)
    if token:
        cabecera = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        entorno.update({"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
                        "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {cabecera}", "GIT_TERMINAL_PROMPT": "0"})
    return entorno


def _arbol(archivos: dict) -> str:
    """El árbol de git con esos archivos (rutas con carpetas), escrito en el repositorio local; devuelve su sha."""
    carpetas = {}
    for ruta, datos in archivos.items():
        sha = _git("hash-object", "-w", "--stdin", entrada=datos).decode().strip()
        *partes, nombre = ruta.split("/")
        carpetas.setdefault(tuple(partes), []).append(("100644", "blob", sha, nombre))
    todas = set()
    for partes in list(carpetas):
        for i in range(len(partes)):
            todas.add(partes[:i])
    for partes in todas:
        carpetas.setdefault(partes, [])
    for partes in sorted(carpetas, key=len, reverse=True):
        entradas = carpetas[partes]
        texto = "".join(f"{modo} {tipo} {sha}\t{nombre}\0" for modo, tipo, sha, nombre in entradas)
        sha = _git("mktree", "-z", entrada=texto.encode("utf-8")).decode().strip()
        if partes:
            carpetas[partes[:-1]].append(("040000", "tree", sha, partes[-1]))
        else:
            return sha
    return _git("mktree", "-z", entrada=b"").decode().strip()


def _arbol_con(base: str, ruta: str, datos: bytes) -> str:
    """El árbol de `base` con `ruta` cambiado por `datos`, con un índice de git aparte (no toca el de trabajo)."""
    carpeta_git = os.path.abspath(_git("rev-parse", "--git-dir").decode().strip())
    indice = dict(os.environ, GIT_INDEX_FILE=os.path.join(carpeta_git, "publicar-index"))
    try:
        _git("read-tree", base, entorno=indice)
        sha = _git("hash-object", "-w", "--stdin", entrada=datos).decode().strip()
        _git("update-index", "--add", "--cacheinfo", f"100644,{sha},{ruta}", entorno=indice)
        return _git("write-tree", entorno=indice).decode().strip()
    finally:
        try:
            os.remove(indice["GIT_INDEX_FILE"])
        except OSError:
            pass


def _commit(arbol: str, mensaje: str, padres=()) -> str:
    entorno = dict(os.environ, GIT_AUTHOR_NAME="github-actions[bot]",
                   GIT_AUTHOR_EMAIL="41898282+github-actions[bot]@users.noreply.github.com",
                   GIT_COMMITTER_NAME="github-actions[bot]",
                   GIT_COMMITTER_EMAIL="41898282+github-actions[bot]@users.noreply.github.com")
    argumentos = ["commit-tree", arbol, "-m", mensaje]
    for padre in padres:
        argumentos += ["-p", padre]
    return _git(*argumentos, entorno=entorno).decode().strip()


def _leer_de_git(revision: str, ruta: str):
    salida = subprocess.run(["git", "show", f"{revision}:{ruta}"], capture_output=True)
    return salida.stdout if salida.returncode == 0 else None


def _main(remoto: str, entorno) -> str:
    _git("fetch", "--quiet", remoto, "+refs/heads/main:refs/remotes/publicar/main", entorno=entorno)
    return _git("rev-parse", "refs/remotes/publicar/main").decode().strip()


def _sueltos_de(revision: str) -> dict:
    """Los archivos sueltos de `revision`; antes de la migración, los de partir su `catalogo.json` en memoria."""
    archivos = permisos.archivos_sueltos(revision)
    if sueltos.migrado(archivos):
        return archivos
    try:
        catalogo = lector_app.leer(_leer_de_git(revision, permisos.RUTA_CATALOGO) or b"")
        return particion.partir(catalogo)
    except (lector_app.JsonIlegible, particion.ErrorParticion) as error:
        raise ErrorPublicar(f"El `{permisos.RUTA_CATALOGO}` de `main` no se puede partir para el índice: {error}") from None


def regenerar_catalogo(api, remoto: str, entorno, aviso) -> str:
    """Deja en `main` el `catalogo.json` regenerado si hace falta. Devuelve el `main` final."""
    for _ in range(INTENTOS):
        base = _main(remoto, entorno)
        archivos = permisos.archivos_sueltos(base)
        if not sueltos.migrado(archivos):
            return base
        datos = catalogo_regenerado(archivos, _leer_de_git(base, permisos.RUTA_CATALOGO))
        if datos is None:
            return base
        arbol = _arbol_con(base, permisos.RUTA_CATALOGO, datos)
        version = json.loads(datos)["versionCatalogo"]
        commit = _commit(arbol, f"Catálogo para las ≤0.2.x regenerado (versión {version})", [base])
        _git("push", "--quiet", "--force", remoto, f"{commit}:refs/heads/{RAMA_CATALOGO}", entorno=entorno)
        propuesta = _propuesta_del_catalogo(api, version)
        api("POST", "/check-runs", {"name": COMPROBACION, "head_sha": commit, "status": "completed",
                                    "conclusion": "success",
                                    "output": {"title": "Catálogo regenerado por el robot",
                                               "summary": "Sale entero de los archivos sueltos de `main`."}})
        if _main(remoto, entorno) != base:
            continue  # `main` se ha movido: se vuelve a juntar con lo último
        hecho = api("PUT", f"/pulls/{propuesta}/merge", {"sha": commit, "merge_method": "squash"},
                    tolerar=(405, 409, 422))
        if hecho is not None:
            aviso(f"Catálogo regenerado (versión {version}) y publicado con la propuesta #{propuesta}.")
            return _main(remoto, entorno)
    raise ErrorPublicar("`main` se ha movido varias veces seguidas mientras se regeneraba el catálogo; la siguiente "
                        "publicación lo intentará otra vez.")


def _propuesta_del_catalogo(api, version: int) -> int:
    """La propuesta abierta de `robot/catalogo` hacia `main` de este mismo repositorio, o una nueva. Una abierta con otra
    base o desde otro repositorio se cierra: fusionarla llevaría el catálogo a otra rama (o la bloquearía)."""
    repositorio = api("GET", "")
    dueno, nombre = repositorio["owner"]["login"], repositorio["full_name"]
    abiertas = api("GET", f"/pulls?state=open&head={dueno}:{RAMA_CATALOGO}") or []
    for pr in abiertas:
        buena = ((pr.get("base") or {}).get("ref") == "main"
                 and ((pr.get("head") or {}).get("repo") or {}).get("full_name") == nombre
                 and (pr.get("head") or {}).get("ref") == RAMA_CATALOGO)
        if buena:
            return pr["number"]
        api("PATCH", f"/pulls/{pr['number']}", {"state": "closed"})
    return api("POST", "/pulls", {"title": f"Catálogo para las ≤0.2.x (versión {version})", "head": RAMA_CATALOGO,
                                  "base": "main", "body": "Lo regenera el robot (trabajo `publicar`) a partir de "
                                  "`juegos/` y `canales/<canal>/parches/`. Se fusiona solo."})["number"]


def escribir_publicado(remoto: str, entorno, base: str, aviso) -> bool:
    """Escribe la rama `publicado` con lo de `base`. False si ya estaba igual."""
    archivos = _sueltos_de(base)
    try:
        catalogo = lector_app.leer(_leer_de_git(base, permisos.RUTA_CATALOGO) or b"")
    except lector_app.JsonIlegible:
        catalogo = None
    ahora = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    nuevos = archivos_publicados(archivos, catalogo if isinstance(catalogo, dict) else None, base, ahora)
    anterior = None
    if subprocess.run(["git", "fetch", "--quiet", remoto, f"+refs/heads/{RAMA_PUBLICADO}:refs/remotes/publicar/publicado"],
                      capture_output=True, env=entorno).returncode == 0:
        anterior = _leer_de_git("refs/remotes/publicar/publicado", "indice.json")
    if anterior is not None and _sin_fecha(anterior) == _sin_fecha(nuevos["indice.json"]):
        return False
    commit = _commit(_arbol(nuevos), f"Publicado desde main {base[:7]}")
    _git("push", "--quiet", "--force", remoto, f"{commit}:refs/heads/{RAMA_PUBLICADO}", entorno=entorno)
    aviso(f"Rama `{RAMA_PUBLICADO}` escrita desde `main` {base[:7]} ({len(nuevos) - 1} trozos).")
    return True


def main() -> int:
    repositorio = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GITHUB_TOKEN"]
    remoto = f"https://github.com/{repositorio}.git"
    entorno = _entorno_con_token(token)
    api = permisos.crear_api(repositorio, token)
    try:
        base = regenerar_catalogo(api, remoto, entorno, permisos.resumen)
        if not escribir_publicado(remoto, entorno, base, permisos.resumen):
            permisos.resumen("Nada nuevo que publicar.")
    except ErrorPublicar as error:
        permisos.resumen(f"### ⚠️ No se ha publicado\n\n{error}")
        return 1
    except Exception as error:  # noqa: BLE001 — cualquier fallo tiene que verse: si no, `publicado` se queda viejo
        permisos.resumen(f"### ⚠️ No se ha publicado (error inesperado)\n\n`{type(error).__name__}`: "
                         f"{str(error)[:500]}")
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
