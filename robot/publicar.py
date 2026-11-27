"""Trabajo `publicar` (fase B de los canales, `docs/canales.md` §1.5, §1.6 y §1.7).

Tras cada fusión en `main` (y a mano, o cuando el Dueño sube algo directamente):

1. **Regenera `catalogo/catalogo.json`** (esquema 1, el que leen las ≤0.2.x) juntando los archivos sueltos de `main`
   (`particion.juntar`), con `versionCatalogo` + 1, si lo que dice ha cambiado. Lo hace con una propuesta propia
   (rama `robot/catalogo`) que se aprueba y se fusiona sola: su contenido sale entero de `main`, así que no hay nada
   que juzgar. Desde la fase D, en la misma propuesta y con la misma `versionCatalogo`, **`catalogo/canales.json`**:
   de cada canal, lo que la app necesita para fiarse de él (`estado`, `verificado`, `paquetes`, `adultos`) y, si
   los tiene, sus `idAnteriores` (solo los @, para avisar al pedir un canal nuevo de uno que ya existió). Está en
   `main`, que está protegida, así que de él sale la lista blanca de descargas de cada canal; `publicado` no. Como las propuestas que abre GitHub Actions no lanzan flujos de trabajo, el propio trabajo deja la
   comprobación `permisos` en verde en ese commit antes de fusionarla.
2. **Escribe la rama `publicado`**: `indice.json` y el índice por juego de Programa › Juegos originales,
   `programa/juegos/<xx>.json` (256 trozos por el SHA-256 del id). Desde la fase C, también lo que lee la app 0.3.0:
   `juegos/<xx>.json` (cada juego con un parche ligero por canal), `detalle/<juego>/<canal>.json` (el juego entero,
   con huellas y versiones), `canales/<xx>.json`, `logos/<canal>.<ext>` y `etiquetas.json`; el índice sigue en
   esquema 1 (las 0.2.x ignoran los trozos que no conocen) y añade `grupo`. Desde la fase D, también
   `miembros/<xx>.json` (los canales de cada cuenta, para el selector de Modo equipo) y `buscar-canales.json` (el
   directorio de canales). Es un único commit sin padres que
   sustituye al anterior (la rama no crece). Si nada ha cambiado, no escribe.

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

import re

import lector_app
import listas
import particion
import permisos
import solicitudes
import sueltos

RAMA_PUBLICADO = "publicado"
RAMA_CATALOGO = "robot/catalogo"
TOPE_ARCHIVO = 8 * 1024 * 1024  # ningún archivo publicado pasa de aquí (el tope del parcheador al descargar)
COMPROBACION = "permisos"       # la comprobación obligatoria de `main`
INTENTOS = 3


class ErrorPublicar(RuntimeError):
    """No se puede publicar sin dejar algo mal: se para y se dice por qué (el `main` sigue como estaba)."""


# ───────────────────────────────────────── El catálogo de las ≤0.2.x ─────────────────────────────────────────

RUTA_CANALES_MAIN = permisos.RUTA_CANALES_MAIN
# Unos 530 bytes por canal en el peor caso (@ de 20, `bloqueado` y 3 repositorios de nombre máximo): 4 MB dan para
# unos 7 900, más del doble de los 5 000 previstos. La app tiene el mismo tope.
TOPE_CANALES_MAIN = 4 * 1024 * 1024


def canales_para_main(archivos: dict, con_anteriores: bool = True) -> list:
    """Las entradas de `catalogo/canales.json`: cada canal con un `canal.json` válido en `main`, ordenados por id.

    Con `con_anteriores`, la de un canal que ha cambiado de @ lleva además `idAnteriores`: la lista de sus @ de antes
    (solo los que valen como @, sin repetir y sin el actual, en el orden de su `canal.json`). Un canal sin @ anteriores
    no lleva el campo, así que su entrada queda igual que antes."""
    entradas, _ = canales_publicados(archivos)
    resultado = []
    for cid, c in sorted(entradas.items()):
        entrada = {"id": cid, "estado": c["estado"], "verificado": c["verificado"], "paquetes": c["paquetes"],
                   "adultos": c["adultos"]}
        if con_anteriores and (anteriores := _ids_anteriores(archivos, cid)):
            entrada["idAnteriores"] = anteriores
        resultado.append(entrada)
    return resultado


def _ids_anteriores(archivos: dict, cid: str) -> list:
    """Los @ de `idAnteriores` del `canal.json` de ese canal en `main` (lo que no vale, fuera)."""
    datos = archivos.get(f"canales/{cid}/canal.json")
    canal = _objeto(datos) if datos is not None else None
    filas = canal.get("idAnteriores") if canal is not None else None
    vistos = []
    for fila in filas if isinstance(filas, list) else []:
        anterior = fila.get("id") if isinstance(fila, dict) else None
        if isinstance(anterior, str) and permisos.canales.ID_CANAL.match(anterior) and anterior != cid and anterior not in vistos:
            vistos.append(anterior)
    return vistos


def _canales_de_main(datos):
    """(versionCatalogo, canales) del `catalogo/canales.json` de `main`, o (None, None) si no hay o no se lee."""
    objeto = _objeto(datos) if datos is not None else None
    if objeto is None:
        return None, None
    return objeto.get("versionCatalogo"), objeto.get("canales")


def regenerados(archivos: dict, catalogo_main: bytes | None, canales_main: bytes | None, avisos: list | None = None):
    """{ruta: bytes} de lo que hay que dejar en `main` (`catalogo.json` y `catalogo/canales.json`, siempre los dos y
    con la misma versión), o None si ya dicen lo mismo. Si solo cambian los canales, el catálogo sube de versión igual:
    la app usa `canales.json` solo si su versión es la del catálogo que tiene.

    Si `canales.json` pasara de `TOPE_CANALES_MAIN`, no se escribe y no frena el catálogo: sale solo `catalogo.json`
    (si cambia) y el motivo va a `avisos`. La app, con un `canales.json` de otra versión, se queda con el oficial y lo
    instalado. Por los canales solos no se sube la versión (si no, subiría en cada publicación).

    Los `idAnteriores` son solo una ayuda para la app: si con ellos no cabe, se escribe sin ellos (y se avisa), que
    la lista blanca importa más."""
    canales = canales_para_main(archivos)
    version_canales, canales_antes = _canales_de_main(canales_main)
    catalogo = catalogo_regenerado(archivos, catalogo_main)

    def cabe(lista):
        # El tamaño casi no depende de la versión: se mide con la mayor posible para no quedarse corto.
        return len(_json({"esquema": 1, "versionCatalogo": lector_app.VERSION_MAXIMA, "canales": lista})) <= TOPE_CANALES_MAIN

    if not cabe(canales) and any("idAnteriores" in c for c in canales):
        canales = canales_para_main(archivos, con_anteriores=False)
        if cabe(canales) and avisos is not None:
            avisos.append(f"`{RUTA_CANALES_MAIN}` pasaría de {TOPE_CANALES_MAIN // 1048576} MB con los `idAnteriores`: "
                          "se escribe sin ellos (el parcheador no avisará al pedir un @ que ya fue de otro canal).")
    if not cabe(canales):
        if avisos is not None:
            avisos.append(f"`{RUTA_CANALES_MAIN}` pasaría de {TOPE_CANALES_MAIN // 1048576} MB ({len(canales)} canales): "
                          "no se actualiza, y el parcheador solo ofrece el canal oficial hasta que se arregle.")
        return None if catalogo is None else {permisos.RUTA_CATALOGO: catalogo}
    if catalogo is None:
        version = lector_app.leer(catalogo_main).get("versionCatalogo")
        if canales_antes == canales and version_canales == version:
            return None
        catalogo = catalogo_regenerado(archivos, catalogo_main, forzar=True)
    version = json.loads(catalogo)["versionCatalogo"]
    datos = _json({"esquema": 1, "versionCatalogo": version, "canales": canales})
    return {permisos.RUTA_CATALOGO: catalogo, RUTA_CANALES_MAIN: datos}


def catalogo_regenerado(archivos: dict, catalogo_main: bytes | None, forzar: bool = False):
    """Los bytes del `catalogo.json` nuevo, o None si el de `main` ya dice lo mismo (sin contar la versión) y no se
    pide `forzar` (subir la versión igual).

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
    if not forzar and isinstance(actual, dict) and particion.mismo_catalogo(dict(actual, versionCatalogo=0),
                                                                           dict(nuevo, versionCatalogo=0)):
        return None
    errores = lector_app.errores_de_la_app(nuevo)
    if errores:
        raise ErrorPublicar("El catálogo juntado no lo podría leer el parcheador: " + "; ".join(errores[:5]))
    datos = permisos.canales.escribir_como_la_app(nuevo).encode("utf-8")
    if len(datos) > TOPE_ARCHIVO:
        raise ErrorPublicar(f"El catálogo juntado pesa {len(datos) / 1048576:.1f} MB y el máximo son 8 MB.")
    return datos


# ───────────────────────────────────────── El Historial global ─────────────────────────────────────────
#
# `historial/central/<AAAA-MM>.json` en `main` (docs/canales.md §1): una fila por cada juego nuevo, edición nueva o
# cambio en la ficha central que un canal ha publicado (directo si está verificado, o aprobado por el Dueño). La fila
# sale del mensaje que el robot pone al fusionar (`solicitudes.linea_historial`) y de lo que cambió ese commit en
# `juegos/<juego>/`. Va en la misma propuesta que el catálogo. Las filas que ya están en `main` no se recalculan.

CARPETA_HISTORIAL = "historial/central/"
TOPE_HISTORIAL = 2 * 1024 * 1024   # por mes; la app tiene el mismo tope. Si no cabe, se quedan las más nuevas.
TOPE_CAMBIOS_FILA = 50             # archivos de `juegos/<juego>/` por fila (y campos por archivo)
TOPE_COMPROBACIONES = 50          # propuestas que se preguntan a GitHub en cada pasada (el resto, en la siguiente)
TOPE_LINEA = 4096
_LINEA_HISTORIAL = re.compile(re.escape(solicitudes.MARCA_HISTORIAL) + r"(\{.*\})[ \t]*\Z")
_CUENTA = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})\Z")
_MES = re.compile(r"^historial/central/(\d{4}-\d{2})\.json\Z")


def fila_de_la_linea(mensaje: str):
    """Los datos de la última línea `Historial-central:` del mensaje, validados, o None."""
    # Por líneas de verdad (`\n`; no `splitlines()`, que también corta en \x1c, \u2028…), la marca al principio.
    lineas = [m.group(1) for linea in (mensaje or "").split("\n")
              if len(linea) <= TOPE_LINEA and (m := _LINEA_HISTORIAL.fullmatch(linea.rstrip("\r")))]
    if not lineas:
        return None
    try:
        # El mismo JSON estricto que el catálogo: sin claves repetidas, sin NaN ni números enormes.
        datos = lector_app.leer(lineas[-1])
    except lector_app.JsonIlegible:
        return None
    if not isinstance(datos, dict) or datos.get("v") != 1:
        return None
    canal, juego, cuenta = datos.get("canal"), datos.get("juego"), datos.get("cuenta")
    cuenta_id, propuesta, tipo = datos.get("cuentaId"), datos.get("propuesta"), datos.get("tipo")
    if not (isinstance(canal, str) and permisos.canales.ID_CANAL.match(canal)
            and isinstance(juego, str) and len(juego) <= 64 and permisos.ID_VALIDO.match(juego)
            and isinstance(cuenta, str) and _CUENTA.match(cuenta)
            and type(cuenta_id) is int and cuenta_id > 0 and type(propuesta) is int and propuesta > 0
            and tipo in solicitudes.DE_PROGRAMA and isinstance(datos.get("directa"), bool)):
        return None
    return {"canal": canal, "cuenta": cuenta, "cuentaId": cuenta_id, "tipo": tipo, "juego": juego,
            "directa": datos["directa"], "propuesta": propuesta}


def _campos(antes: bytes | None, despues: bytes | None):
    """Las claves de primer nivel que cambian entre dos JSON (`nuevo`/`borrado` si falta uno; `?` si no se leen)."""
    if antes is None:
        return "nuevo"
    if despues is None:
        return "borrado"
    a, d = _objeto(antes), _objeto(despues)
    if a is None or d is None:
        return "?"
    campos = sorted(c for c in set(a) | set(d) if a.get(c, _NADA) != d.get(c, _NADA))
    return campos[:TOPE_CAMBIOS_FILA]


_NADA = object()


def cambios_del_commit(sha: str, juego: str) -> dict:
    """{archivo dentro de `juegos/<juego>/`: campos} de lo que cambió el commit `sha` respecto a su primer padre."""
    carpeta = f"juegos/{juego}/"
    salida = subprocess.run(["git", "diff-tree", "-r", "-z", "--no-commit-id", "--name-only", "--no-renames",
                             f"{sha}^1", sha, "--", carpeta], capture_output=True)
    if salida.returncode != 0:
        return {}
    rutas = sorted(r for r in salida.stdout.decode("utf-8", errors="replace").split("\0") if r.startswith(carpeta))
    cambios = {}
    for ruta in rutas[:TOPE_CAMBIOS_FILA]:
        archivo = ruta[len(carpeta):]
        if archivo.endswith(".json"):
            cambios[archivo] = _campos(_leer_de_git(f"{sha}^1", ruta), _leer_de_git(sha, ruta))
        else:
            cambios[archivo] = "borrado" if _leer_de_git(sha, ruta) is None else "cambiado"
    return cambios


def _commits_con_historial(revision: str) -> list:
    """[(sha, fecha UTC, mensaje)] de los commits de `main` (primer padre) con la línea del historial, del más viejo
    al más nuevo."""
    salida = _git("log", "--first-parent", "--reverse", "-z", "--format=%H%x1f%ct%x1f%B", "--fixed-strings",
                  f"--grep={solicitudes.MARCA_HISTORIAL.strip()}", revision).decode("utf-8", errors="replace")
    commits = []
    for entrada in (e for e in salida.split("\0") if e.strip()):
        partes = entrada.strip("\n").split("\x1f", 2)
        if len(partes) != 3:
            continue
        fecha = datetime.datetime.fromtimestamp(int(partes[1]), datetime.timezone.utc)
        commits.append((partes[0], fecha.strftime("%Y-%m-%dT%H:%M:%SZ"), partes[2]))
    return commits


def _historial_de_main(revision: str) -> dict:
    """{mes: {"filas": [...], "recortadas": n}} de los `historial/central/<AAAA-MM>.json` de `revision` (lo ilegible,
    vacío: se rehace)."""
    salida = subprocess.run(["git", "ls-tree", "-r", "-z", "--name-only", "--full-tree", revision, "--",
                             CARPETA_HISTORIAL], capture_output=True)
    meses = {}
    for ruta in salida.stdout.decode("utf-8", errors="replace").split("\0"):
        mes = _MES.match(ruta)
        if not mes:
            continue
        datos = _objeto(_leer_de_git(revision, ruta) or b"")
        filas = datos.get("filas") if isinstance(datos, dict) else None
        if isinstance(filas, list):
            recortadas = datos.get("recortadas")
            meses[mes.group(1)] = {"filas": [f for f in filas if isinstance(f, dict)],
                                   "recortadas": recortadas if type(recortadas) is int and recortadas > 0 else 0}
    return meses


def _confirmada(api, fila: dict, sha: str):
    """Si GitHub confirma la fila: la propuesta está fusionada justo en ese commit y es de esa cuenta (id y nombre).
    True o False; None si no se ha podido preguntar (se vuelve a intentar en la siguiente pasada)."""
    try:
        datos = api("GET", f"/pulls/{fila['propuesta']}", tolerar=(404,))
    except RuntimeError:
        return None
    if not isinstance(datos, dict):
        return False
    usuario = datos.get("user")
    return (datos.get("merged") is True and datos.get("merge_commit_sha") == sha and isinstance(usuario, dict)
            and type(usuario.get("id")) is int and usuario["id"] == fila["cuentaId"]
            and isinstance(usuario.get("login"), str) and usuario["login"].lower() == fila["cuenta"].lower())


def _nuevos(commits: list, meses: dict) -> list:
    """Los commits posteriores a la fila más nueva que ya está en `main` (la marca de agua). Lo de antes ya se miró:
    las filas recortadas de un mes lleno no vuelven a entrar, y lo rechazado antes de una fila buena no se vuelve a
    preguntar."""
    conocidos = {f.get("commit") for mes in meses.values() for f in mes["filas"]}
    ultimo = max((i for i, (sha, _, _) in enumerate(commits) if sha in conocidos), default=None)
    if ultimo is not None:
        return commits[ultimo + 1:]
    # Ninguna fila de `main` está en la historia (reescrita): lo de la misma fecha o después de la más nueva.
    fechas = [f["fecha"] for mes in meses.values() for f in mes["filas"] if isinstance(f.get("fecha"), str)]
    if not fechas:
        return commits
    tope = max(fechas)
    return [c for c in commits if c[1] >= tope and c[0] not in conocidos]


def historial_central(revision: str, api, avisos: list | None = None) -> dict:
    """{ruta: bytes} de los `historial/central/<AAAA-MM>.json` que hay que escribir en `main` (solo los que cambian)."""
    def avisar(texto):
        if avisos is not None:
            avisos.append(texto)

    meses = _historial_de_main(revision)
    tocados = set()
    comprobadas = 0
    for sha, fecha, mensaje in _nuevos(_commits_con_historial(revision), meses):
        fila = fila_de_la_linea(mensaje)
        if fila is None:
            avisar(f"El commit {sha[:7]} lleva una línea `{solicitudes.MARCA_HISTORIAL.strip()}` que no se entiende: "
                   "no sale en el Historial global.")
            continue
        cambios = cambios_del_commit(sha, fila["juego"])
        if not cambios and fila["tipo"] != "edicion":
            continue  # no cambió nada de lo central: no hay nada que contar
        if comprobadas >= TOPE_COMPROBACIONES:
            avisar("Quedan filas del Historial global por comprobar: siguen en la próxima pasada.")
            break
        comprobadas += 1
        confirmada = _confirmada(api, fila, sha)
        if confirmada is None:
            # Se para aquí (no se salta): lo de después espera a que esta se pueda comprobar.
            avisar(f"No se ha podido preguntar a GitHub por la propuesta #{fila['propuesta']}: el Historial global "
                   "sigue en la próxima pasada.")
            break
        if not confirmada:
            avisar(f"El commit {sha[:7]} dice venir de la propuesta #{fila['propuesta']} de @{fila['cuenta']}, pero "
                   "GitHub no lo confirma: no sale en el Historial global.")
            continue
        fila = {"fecha": fecha, **fila, "commit": sha, "cambios": cambios}
        mes = fecha[:7]
        meses.setdefault(mes, {"filas": [], "recortadas": 0})["filas"].append(fila)
        tocados.add(mes)
    resultado = {}
    for mes in sorted(tocados):
        filas, recortadas = meses[mes]["filas"], meses[mes]["recortadas"]
        # Por fecha y, en el mismo segundo, en el orden de `main` (la ordenación es estable).
        filas.sort(key=lambda f: str(f.get("fecha")))

        def texto():
            datos = {"esquema": 1, "mes": mes, "filas": filas}
            if recortadas:
                datos["recortadas"] = recortadas
            return _json(datos)
        datos = texto()
        while len(datos) > TOPE_HISTORIAL and filas:
            quitar = max(1, len(filas) // 10)
            filas, recortadas = filas[quitar:], recortadas + quitar
            datos = texto()
        ruta = f"{CARPETA_HISTORIAL}{mes}.json"
        if datos == _leer_de_git(revision, ruta):
            continue
        if recortadas > meses[mes]["recortadas"]:
            avisar(f"`{ruta}` no cabe en {TOPE_HISTORIAL // 1048576} MB: se quedan las {len(filas)} filas más nuevas "
                   f"({recortadas} recortadas).")
        resultado[ruta] = datos
    return resultado


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


def _hash(datos: bytes) -> str:
    return "sha256:" + hashlib.sha256(datos).hexdigest()


# Lo que no va en la lista ni en la ficha (fase C): solo en `detalle/<juego>/<canal>.json`.
CAMPOS_SOLO_DETALLE = ("huella", "huellasParcheadas", "versiones")
EXTENSION_LOGO = {"png": "png", "webp": "webp", "jpeg": "jpg"}


def _canales_vetados(archivos: dict) -> dict:
    """{@: motivo} de `normas/lista-negra/canales.json` (vacío si no hay). Si no se puede leer, no se publica nada
    (falla en cerrado: publicar sin ella sacaría como activos canales bloqueados)."""
    try:
        return listas.canales_vetados(archivos.get)
    except listas.ListaIlegible as error:
        raise ErrorPublicar(f"La lista negra de canales de `main` no se puede leer: {error}") from None


def canales_publicados(archivos: dict) -> dict:
    """{id: entrada de `canales/<xx>.json`} de cada canal con un `canal.json` que se puede leer, cuyo `id` es el de su
    carpeta y con un `estado` conocido; y {ruta: bytes} de los logos que valen. Un canal dañado no entra (ni sus
    parches): no tumba la publicación. Un canal de la lista negra general de canales sale `bloqueado` aunque su
    `canal.json` diga otra cosa."""
    entradas, logos = {}, {}
    vetados = _canales_vetados(archivos)
    for ruta, datos in archivos.items():
        partes = ruta.split("/")
        if len(partes) != 3 or partes[0] != "canales" or partes[2] != "canal.json":
            continue
        cid = partes[1]
        if not permisos.canales.ID_CANAL.match(cid):
            continue
        canal = _objeto(datos)
        if canal is None or canal.get("id") != cid or canal.get("estado") not in particion.ESTADOS_JUEGO:
            continue
        verificacion = canal.get("verificacion") if isinstance(canal.get("verificacion"), dict) else {}
        logo = None
        nombre_logo = canal.get("logo")
        if isinstance(nombre_logo, str) and "/" not in nombre_logo and nombre_logo.endswith(permisos.canales.EXTENSIONES_LOGO):
            imagen = archivos.get(f"canales/{cid}/{nombre_logo}")
            tipo = permisos.canales.tipo_de_imagen(imagen) if imagen is not None else None
            if tipo is not None and len(imagen) <= permisos.canales.TOPE_LOGO:
                destino = f"logos/{cid}.{EXTENSION_LOGO[tipo]}"
                logos[destino] = imagen
                logo = {"ruta": destino, "tamano": len(imagen), "hash": _hash(imagen)}
        paquetes = canal.get("paquetes") if isinstance(canal.get("paquetes"), list) else []
        paquetes = sorted({p for p in paquetes if isinstance(p, str) and permisos.canales.REPOSITORIO.match(p)})
        entradas[cid] = {
            "id": cid,
            "nombre": canal["nombre"] if isinstance(canal.get("nombre"), str) else cid,
            "descripcion": canal["descripcion"] if isinstance(canal.get("descripcion"), str) else "",
            "verificado": verificacion.get("verificado") is True,
            "adultos": canal.get("adultos") is True,
            "estado": "bloqueado" if cid in vetados else canal["estado"],
            "oculto": canal.get("oculto") is True,
            "contacto": canal["contacto"] if isinstance(canal.get("contacto"), dict) else {},
            "logo": logo,
            # Los repositorios de paquetes del canal (fase D): la lista blanca de descargas de la app.
            "paquetes": paquetes[:permisos.canales.MAX_PAQUETES],
        }
    _sin_repositorios_ajenos(entradas)
    return entradas, logos


def _sin_repositorios_ajenos(entradas: dict):
    """Por si acaso (el robot ya no lo acepta; podría venir de un arreglo a mano): un canal que no es el oficial pierde
    los repositorios de OrnizStudio, y un repositorio que declaran varios canales no se queda en ninguno (sin distinguir
    mayúsculas). Mejor sin descargas que con las de otro."""
    cuantos = {}
    for entrada in entradas.values():
        for p in entrada["paquetes"]:
            cuantos[p.casefold()] = cuantos.get(p.casefold(), 0) + 1
    for cid, entrada in entradas.items():
        entrada["paquetes"] = [p for p in entrada["paquetes"] if cuantos[p.casefold()] == 1 and not (
            cid != permisos.canales.CANAL_OFICIAL
            and permisos.canales.dueno_de_repositorio(p) == permisos.canales.ORGANIZACION_OFICIAL)]


def _ligero(juego: dict) -> dict:
    """El juego sin huellas ni versiones en ninguna edición (lo de la lista y la ficha)."""
    ligero = dict(juego)
    if isinstance(ligero.get("ediciones"), list):
        ligero["ediciones"] = [{k: v for k, v in e.items() if k not in CAMPOS_SOLO_DETALLE} if isinstance(e, dict) else e
                               for e in ligero["ediciones"]]
    return ligero


def juegos_publicados(archivos: dict, canales: dict):
    """({id: entrada de `juegos/<xx>.json`}, {ruta: bytes} de `detalle/<juego>/<canal>.json`).

    Cada parche se junta solo con su juego y sus ediciones (`particion.juntar(…, todos=True)`): uno dañado no entra y
    no arrastra a los demás. Los parches de un canal `bloqueado` o sin `canal.json` válido no entran."""
    por_juego, ediciones = {}, {}
    for ruta in archivos:
        tipo = sueltos.tipo_de_ruta(ruta)
        if tipo is None:
            continue
        if tipo[0] == "parche":
            canal = canales.get(tipo[1])
            if canal is not None and canal["estado"] != "bloqueado":
                por_juego.setdefault(tipo[2], []).append((tipo[1], ruta))
        elif tipo[0] == "edicion":
            ediciones.setdefault(tipo[1], []).append(ruta)
    entradas, detalles = {}, {}
    for jid, parches in sorted(por_juego.items()):
        ruta_juego = f"juegos/{jid}/juego.json"
        central = _objeto(archivos.get(ruta_juego, b""))
        if central is None or central.get("id") != jid:
            continue
        estado = central.get("estado", "activo")
        if estado not in particion.ESTADOS_JUEGO:
            continue
        base = {ruta_juego: archivos[ruta_juego], **{r: archivos[r] for r in ediciones.get(jid, ())}}
        lista = []
        for cid, ruta_parche in sorted(parches):
            try:
                juntado = particion.juntar({**base, ruta_parche: archivos[ruta_parche]}, 0, canal=cid, todos=True)
            except particion.ErrorParticion:
                continue
            if len(juntado["juegos"]) != 1:
                continue
            juego = juntado["juegos"][0]
            ruta_detalle = f"detalle/{jid}/{cid}.json"
            datos = _json({"esquema": 1, "canal": cid, "juego": juego})
            detalles[ruta_detalle] = datos
            lista.append({"canal": cid, "detalle": _hash(datos), "juego": _ligero(juego)})
        if lista:
            entradas[jid] = {"id": jid, "estado": estado, "parches": lista}
    return entradas, detalles


def miembros_publicados(archivos: dict, canales: dict, hoy: datetime.date) -> dict:
    """{id de cuenta: entrada de `miembros/<xx>.json`}: los canales `activo` y `retirado` de cada cuenta, con su rol y
    su estado. No salen los canales `bloqueado` ni las cuentas vetadas (en la lista negra general o en la del canal).
    Un `miembros.json` o una lista negra del canal que no se lee deja fuera ese canal; un trozo de la lista negra
    general que no se lee deja fuera a sus cuentas (es solo para enseñar: el robot mira `main` en cada propuesta)."""
    consultas = listas.Consultas(archivos.get, hoy)  # cada trozo de la lista negra se lee una vez

    def vetada(cuenta_id):
        try:
            return consultas.veto(cuenta_id) is not None
        except listas.ListaIlegible:
            return True

    cuentas = {}
    for cid, canal in sorted(canales.items()):
        if canal["estado"] not in ("activo", "retirado"):
            continue
        ruta = f"canales/{cid}/miembros.json"
        ruta_lista = f"canales/{cid}/lista-negra.json"
        try:
            filas, errores = permisos.canales.leer_miembros(
                permisos.canales.leer_json_estricto(archivos.get(ruta) or b"", ruta,
                                                    permisos.canales.TOPES["miembros.json"]), ruta)
            del_canal = {}
            if ruta_lista in archivos:
                lista, errores_lista = permisos.canales.leer_lista_negra(
                    permisos.canales.leer_json_estricto(archivos[ruta_lista], ruta_lista,
                                                        permisos.canales.TOPES["lista-negra.json"]), ruta_lista)
                if errores_lista:
                    continue
                del_canal = lista.usuarios
        except permisos.canales.JsonMalo:
            continue
        if errores:
            continue
        for cuenta_id, m in sorted(filas.items()):
            if cuenta_id in del_canal or vetada(cuenta_id):
                continue
            fila = {"canal": cid, "rol": permisos.canales.TEXTO_ROL[m.rol - 1], "estado": m.estado}
            if m.estado == "invitado" and isinstance(m.fila.get("invitadoPor"), int):
                fila["invitadoPor"] = m.fila["invitadoPor"]
            entrada = cuentas.setdefault(cuenta_id, {"id": cuenta_id, "cuenta": m.cuenta, "canales": []})
            entrada["canales"].append(fila)
    return cuentas


# Personas del equipo que lleva cada canal en `canales/<xx>.json` (la ficha enseña 8 y «Y N más»; `miembrosActivos`
# dice cuántas son en total). 100 cuentas de 39 caracteres son unos 6 KB por canal.
MAX_EQUIPO_PUBLICADO = 100


def ficha_publicada(archivos: dict, cid: str, juegos: dict, hoy: datetime.date):
    """La ficha pública de un canal tal como la lee la app, o None si no tiene `ficha.json` o no vale entera (el robot
    ya no la acepta así; podría venir de un arreglo a mano). Un `destacado` que no es un juego con parche publicado de
    este canal sale null: la ficha no recomienda lo que no se puede instalar."""
    ruta = f"canales/{cid}/ficha.json"
    datos = archivos.get(ruta)
    if datos is None:
        return None
    try:
        ficha = permisos.canales.leer_json_estricto(datos, ruta, permisos.canales.TOPES["ficha.json"])
    except permisos.canales.JsonMalo:
        return None
    if permisos.canales.validar_ficha(ficha, ruta, hoy):
        return None
    destacado = ficha.get("destacado")
    if destacado is not None and not any(p["canal"] == cid for p in juegos.get(destacado, {}).get("parches", [])):
        destacado = None
    return {"descripcion": ficha.get("descripcion", ""), "idiomas": ficha.get("idiomas", []),
            "tipos": ficha.get("tipos", []), "enlaces": ficha.get("enlaces", []), "enCurso": ficha.get("enCurso", []),
            "destacado": destacado}


def equipos_publicados(cuentas: dict) -> dict:
    """{canal: (equipo, total)}: los miembros activos de cada canal (nunca los invitados, ni las cuentas vetadas, que
    ya no están en `cuentas`), del rol más alto al más bajo y luego por cuenta; como mucho `MAX_EQUIPO_PUBLICADO`."""
    por_canal = {}
    for entrada in cuentas.values():
        for fila in entrada["canales"]:
            if fila["estado"] == "activo":
                por_canal.setdefault(fila["canal"], []).append({"cuenta": entrada["cuenta"], "rol": fila["rol"]})
    orden = {rol: i for i, rol in enumerate(reversed(permisos.canales.TEXTO_ROL))}
    return {cid: (sorted(lista, key=lambda m: (orden[m["rol"]], m["cuenta"].casefold(), m["cuenta"]))[:MAX_EQUIPO_PUBLICADO],
                  len(lista)) for cid, lista in por_canal.items()}


def _completar_fichas(archivos: dict, canales: dict, juegos: dict, cuentas: dict, hoy: datetime.date) -> dict:
    """Las entradas de `canales/<xx>.json` con lo que solo enseña la ficha del canal (desde la 0.4.3): `creado`,
    `ficha`, `equipo` y `miembrosActivos`. Va aparte de `canales_publicados` para que nada de esto llegue a
    `catalogo/canales.json` de `main`."""
    equipos = equipos_publicados(cuentas)
    completas = {}
    for cid, entrada in canales.items():
        canal = _objeto(archivos.get(f"canales/{cid}/canal.json", b"")) or {}
        equipo, total = equipos.get(cid, ([], 0))
        completas[cid] = {**entrada,
                          "creado": canal["creado"] if permisos.canales._es_fecha(canal.get("creado")) else None,
                          "ficha": ficha_publicada(archivos, cid, juegos, hoy),
                          "equipo": equipo, "miembrosActivos": total}
    return completas


def buscar_canales(canales: dict, juegos: dict) -> bytes:
    """`buscar-canales.json`: el directorio de canales, todos menos los ocultos, con cuántos juegos tienen parche
    publicado de cada uno."""
    parches = {}
    for juego in juegos.values():
        for parche in juego["parches"]:
            parches[parche["canal"]] = parches.get(parche["canal"], 0) + 1
    return _json({"esquema": 1, "canales": [
        {"id": cid, "nombre": c["nombre"], "verificado": c["verificado"], "estado": c["estado"],
         "adultos": c["adultos"], "parches": parches.get(cid, 0)}
        for cid, c in sorted(canales.items()) if not c["oculto"]]})


def retirados(archivos: dict, canales: dict) -> bytes:
    """`retirados.json`: los juegos (por su `estado` central) y los canales que ya no se ofrecen, para quien los tiene
    instalados. Las ediciones no tienen estado propio: una que ya no se ofrece es la de un juego o un canal de aquí."""
    juegos = []
    for ruta in sorted(archivos):
        tipo = sueltos.tipo_de_ruta(ruta)
        if tipo is None or tipo[0] != "juego":
            continue
        central = _objeto(archivos[ruta])
        if isinstance(central, dict) and central.get("id") == tipo[1] and central.get("estado") in ("retirado", "bloqueado"):
            juegos.append({"id": tipo[1], "estado": central["estado"]})
    return _json({"esquema": 1, "juegos": juegos, "canales": [
        {"id": cid, "estado": c["estado"]} for cid, c in sorted(canales.items()) if c["estado"] != "activo"]})


def _trozos_de_miembros(cuentas: dict) -> dict:
    """`miembros/<xx>.json`, con `<xx>` del SHA-256 del id escrito en decimal y las cuentas ordenadas por id."""
    por_trozo = {}
    for cuenta_id in sorted(cuentas):
        por_trozo.setdefault(listas.trozo(cuenta_id), []).append(cuentas[cuenta_id])
    return {f"miembros/{t}.json": _json({"esquema": 1, "cuentas": lista}) for t, lista in sorted(por_trozo.items())}


def _trozos(prefijo: str, clave: str, entradas: dict) -> dict:
    por_trozo = {}
    for ident, entrada in sorted(entradas.items()):
        por_trozo.setdefault(trozo(ident), []).append(entrada)
    return {f"{prefijo}{t}.json": _json({"esquema": 1, clave: lista}) for t, lista in sorted(por_trozo.items())}


def archivos_publicados(archivos: dict, catalogo: dict | None, main_sha: str, ahora: str) -> dict:
    """{ruta: bytes} de la rama `publicado`: `indice.json`, `programa/juegos/<xx>.json` (fase B) y, para la app 0.3.0,
    `juegos/<xx>.json`, `detalle/<juego>/<canal>.json`, `canales/<xx>.json`, `logos/<canal>.<ext>` y
    `etiquetas.json`; desde la fase D, `miembros/<xx>.json`, `buscar-canales.json` y `retirados.json`. ErrorPublicar si algún archivo
    pasa de 8 MB."""
    resultado = _trozos("programa/juegos/", "juegos", indice_por_juego(archivos))
    canales, logos = canales_publicados(archivos)
    juegos, detalles = juegos_publicados(archivos, canales)
    resultado.update(_trozos("juegos/", "juegos", juegos))
    hoy = datetime.date.fromisoformat(ahora[:10]) if len(ahora) >= 10 else datetime.datetime.now(datetime.timezone.utc).date()
    cuentas = miembros_publicados(archivos, canales, hoy)
    resultado.update(_trozos("canales/", "canales", _completar_fichas(archivos, canales, juegos, cuentas, hoy)))
    resultado.update(_trozos_de_miembros(cuentas))
    if canales:
        resultado["buscar-canales.json"] = buscar_canales(canales, juegos)
        resultado["retirados.json"] = retirados(archivos, canales)
    if particion.RUTA_ETIQUETAS in archivos or isinstance((catalogo or {}).get("etiquetas"), list):
        # Sin ninguna de las dos fuentes (un `main` vacío) no hay nada que decir: la app sigue con el catálogo.
        etiquetas = (_objeto(archivos.get(particion.RUTA_ETIQUETAS, b"")) or {}).get("etiquetas")
        if not isinstance(etiquetas, list):
            etiquetas = (catalogo or {}).get("etiquetas") if isinstance((catalogo or {}).get("etiquetas"), list) else []
        resultado["etiquetas.json"] = _json({"esquema": 1, "etiquetas": etiquetas})
    trozos = {ruta: _hash(datos) for ruta, datos in sorted(resultado.items())}
    resultado.update(detalles)
    resultado.update(logos)
    programa = _objeto(archivos.get(particion.RUTA_PARCHEADOR, b"")) or {}
    resultado["indice.json"] = _json({
        "esquema": 1, "generado": ahora, "main": main_sha,
        "versionCatalogo": (catalogo or {}).get("versionCatalogo"),
        "launcher": programa.get("launcher", (catalogo or {}).get("launcher")),
        "grupo": programa.get("grupo", (catalogo or {}).get("grupo")),
        "trozos": trozos,
    })
    for ruta, datos in sorted(resultado.items()):
        if len(datos) > TOPE_ARCHIVO:
            raise ErrorPublicar(f"`{ruta}` pesa {len(datos) / 1048576:.1f} MB y el máximo de un archivo publicado son "
                                "8 MB: no se publica nada hasta que se reduzca.")
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


def _arbol_con(base: str, cambios: dict) -> str:
    """El árbol de `base` con cada `ruta` de `cambios` cambiada por sus bytes, con un índice de git aparte (no toca el
    de trabajo)."""
    carpeta_git = os.path.abspath(_git("rev-parse", "--git-dir").decode().strip())
    indice = dict(os.environ, GIT_INDEX_FILE=os.path.join(carpeta_git, "publicar-index"))
    try:
        _git("read-tree", base, entorno=indice)
        for ruta, datos in sorted(cambios.items()):
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


def _archivos_de_canales(revision: str) -> dict:
    """{ruta: bytes} de los `canal.json`, `miembros.json`, `lista-negra.json` y las imágenes de la raíz de cada
    `canales/<c>/` (los logos) en `revision`, más la lista negra general (`normas/lista-negra/`), de una vez con
    `git cat-file --batch`. Un trozo de la lista negra general que pasa de su tope sale ilegible (nadie de él sale en
    `miembros/`). Un logo que pasa de su tope no se lee: se cambia por algo que no vale como logo
    (sale `logo: null`). Un `canal.json` que pasa de su tope no se lee (el canal no se publica)."""
    salida = _git("ls-tree", "-r", "-z", "-l", "--full-tree", revision, "--",
                  permisos.canales.CARPETA_CANALES, listas.CARPETA).decode("utf-8", errors="replace")
    pedir, resultado = [], {}
    for entrada in (e for e in salida.split("\0") if e):
        cabecera, ruta = entrada.split("\t", 1)
        modo, tipo, sha, tamano = cabecera.split()
        if ruta.startswith(listas.CARPETA):
            if modo == "100644" and tipo == "blob":
                if int(tamano) > listas.TOPE_TROZO:
                    resultado[ruta] = b"{"
                else:
                    pedir.append((ruta, sha))
            continue
        partes = ruta.split("/")
        if modo != "100644" or tipo != "blob" or len(partes) != 3 or not permisos.canales.ID_CANAL.match(partes[1]):
            continue
        if partes[2] in ("canal.json", "miembros.json", "lista-negra.json", "ficha.json"):
            if int(tamano) <= permisos.canales.TOPES[partes[2]]:
                pedir.append((ruta, sha))
        elif partes[2].endswith(permisos.canales.EXTENSIONES_LOGO):
            if int(tamano) > permisos.canales.TOPE_LOGO:
                resultado[ruta] = b"\0" * (permisos.canales.TOPE_LOGO + 1)
            else:
                pedir.append((ruta, sha))
    if pedir:
        salida = _git("cat-file", "--batch", entrada="".join(f"{sha}\n" for _, sha in pedir).encode())
        i = 0
        for ruta, _sha in pedir:
            fin = salida.index(b"\n", i)
            largo = int(salida[i:fin].split(b" ")[2])
            resultado[ruta] = salida[fin + 1:fin + 1 + largo]
            i = fin + 1 + largo + 1
    return resultado


def _sueltos_de(revision: str) -> dict:
    """Los archivos sueltos de `revision` (antes de la migración, los de partir su `catalogo.json` en memoria), más los
    `canal.json` y los logos de los canales."""
    archivos = permisos.archivos_sueltos(revision)
    if not sueltos.migrado(archivos):
        try:
            catalogo = lector_app.leer(_leer_de_git(revision, permisos.RUTA_CATALOGO) or b"")
            archivos = particion.partir(catalogo)
        except (lector_app.JsonIlegible, particion.ErrorParticion) as error:
            raise ErrorPublicar(f"El `{permisos.RUTA_CATALOGO}` de `main` no se puede partir para el índice: {error}") from None
    for ruta, datos in _archivos_de_canales(revision).items():
        archivos.setdefault(ruta, datos)
    return archivos


def regenerar_catalogo(api, remoto: str, entorno, aviso) -> str:
    """Deja en `main` el `catalogo.json` regenerado si hace falta. Devuelve el `main` final."""
    for _ in range(INTENTOS):
        base = _main(remoto, entorno)
        archivos = permisos.archivos_sueltos(base)
        if not sueltos.migrado(archivos):
            return base
        vetados = _leer_de_git(base, listas.RUTA_CANALES)
        if vetados is not None:
            archivos[listas.RUTA_CANALES] = vetados
        avisos = []
        cambios = regenerados(archivos, _leer_de_git(base, permisos.RUTA_CATALOGO),
                              _leer_de_git(base, RUTA_CANALES_MAIN), avisos)
        historial = historial_central(base, api, avisos)
        for texto in avisos:
            aviso(texto)
        if cambios is None and not historial:
            return base
        cambios = {**(cambios or {}), **historial}
        arbol = _arbol_con(base, cambios)
        version = (json.loads(cambios[permisos.RUTA_CATALOGO])["versionCatalogo"]
                   if permisos.RUTA_CATALOGO in cambios else None)
        titulo = (f"Catálogo para las ≤0.2.x regenerado (versión {version})" if version is not None
                  else "Historial global del programa")
        commit = _commit(arbol, titulo, [base])
        _git("push", "--quiet", "--force", remoto, f"{commit}:refs/heads/{RAMA_CATALOGO}", entorno=entorno)
        propuesta = _propuesta_del_catalogo(api, version)
        api("POST", "/check-runs", {"name": COMPROBACION, "head_sha": commit, "status": "completed",
                                    "conclusion": "success",
                                    "output": {"title": "Catálogo regenerado por el robot",
                                               "summary": "Sale entero de los archivos sueltos de `main`."}})
        if _main(remoto, entorno) != base:
            continue  # `main` se ha movido: se vuelve a juntar con lo último
        # Título y mensaje propios (como en permisos.datos_de_fusion): nada de la rama acaba en el mensaje de `main`.
        hecho = api("PUT", f"/pulls/{propuesta}/merge", {"sha": commit, "merge_method": "squash",
                                                         "commit_title": f"{titulo} (#{propuesta})",
                                                         "commit_message": "Regenerado por el robot."},
                    tolerar=(405, 409, 422))
        if hecho is not None:
            que = f"Catálogo regenerado (versión {version})" if version is not None else "Historial global"
            if historial:
                que += f" con {len(historial)} mes(es) del Historial global" if version is not None else ""
            aviso(f"{que} publicado con la propuesta #{propuesta}.")
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
    titulo = f"Catálogo para las ≤0.2.x (versión {version})" if version is not None else "Historial global del programa"
    return api("POST", "/pulls", {"title": titulo, "head": RAMA_CATALOGO,
                                  "base": "main", "body": "Lo regenera el robot (trabajo `publicar`) a partir de "
                                  "`juegos/`, `canales/<canal>/parches/` y los commits de `main` (Historial global, "
                                  "`historial/central/`). Se fusiona solo."})["number"]


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
