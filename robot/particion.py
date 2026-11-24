"""Fase B de los canales: el catálogo en archivos sueltos (`docs/canales.md` §1.4 y §1.6 en el repositorio de la app).

`partir` reparte un `catalogo/catalogo.json` (esquema 1) en:

- `juegos/<juego>/juego.json`: lo central del juego (títulos, sinopsis, imágenes, detección), su `estado` central
  (`activo`, `retirado`, `bloqueado`), quién lo dio de alta (`alta`) y el orden de sus ediciones;
- `juegos/<juego>/ediciones/<edicion>.json`: lo central de cada edición (nombre, huella, tiendas, lanzamiento…);
- `canales/<canal>/parches/<juego>.json`: lo del canal (visible, orden, estado de la traducción, progreso, opciones,
  versiones, huellas parcheadas…), con una entrada por edición;
- `normas/etiquetas.json`: las etiquetas globales;
- `programa/parcheador.json`: el bloque `launcher` (y el `grupo` del catálogo de antes, que solo leen las ≤0.2.x).

`juntar` hace lo contrario: con esos archivos vuelve a escribir el catálogo de esquema 1 que leen las ≤0.2.x, solo con
los juegos del canal oficial. Partir y volver a juntar da el mismo catálogo (mismos datos; los juegos, en el orden en
que los enseña la app: `orden` y luego `id`).

Cada campo del modelo de la app (`lector_app.MODELO`) va a un solo archivo. Un campo que no está en el modelo es un
error: así nada se pierde por el camino sin que nadie se entere.

Solo usa la biblioteca estándar.
"""

from __future__ import annotations

import json
import re

import lector_app

CANAL_OFICIAL = "ornizen"

RUTA_CATALOGO = "catalogo/catalogo.json"
RUTA_ETIQUETAS = "normas/etiquetas.json"
RUTA_PARCHEADOR = "programa/parcheador.json"

# Qué va a lo central y qué al parche del canal. Entre los dos, todos los campos de `Juego` y `Edicion` del modelo.
JUEGO_CENTRAL = ("id", "titulo", "tituloCorto", "tituloOriginal", "relacionado", "sinopsis", "imagenes", "deteccion")
JUEGO_CANAL = ("habilitado", "disponibilidad", "pruebas", "orden", "etiquetas", "estado", "progreso", "creditos",
               "opciones", "parche")
EDICION_CENTRAL = ("id", "nombre", "grupo", "huella", "ignorar", "ignorados", "lanzar", "tiendas", "restricciones",
                   "avisoRestricciones", "imagenes")
EDICION_CANAL = ("notaEdicion", "disponibilidad", "pruebas", "huellasParcheadas", "estado", "progreso", "parche",
                 "versiones", "etiquetas", "contenido")
# Los campos que el canal puede poner encima de los del juego («Nombre en tu canal», la sinopsis de la traducción).
JUEGO_CANAL_ENCIMA = ("titulo", "sinopsis")

# Lo nuevo de la fase B, que no está en el catálogo de esquema 1.
ESTADOS_JUEGO = ("activo", "retirado", "bloqueado")
ALTA_MIGRADA = {"canal": CANAL_OFICIAL, "cuenta": None, "fecha": None}

# Un id es el nombre de una carpeta o de un archivo: nada que se salga de su sitio ni que Windows no sepa guardar.
ID_VALIDO = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,98}[A-Za-z0-9])?")
RESERVADOS_WINDOWS = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(10)), *(f"lpt{i}" for i in range(10))}

TOPE_JUEGOS = 20_000
TOPE_EDICIONES = 200


class ErrorParticion(ValueError):
    """El catálogo o los archivos sueltos no se pueden partir o juntar sin perder algo: se dice qué y dónde."""


def _comprobar_modelo():
    for tipo, central, canal in (("Juego", JUEGO_CENTRAL, JUEGO_CANAL + ("ediciones",)),
                                 ("Edicion", EDICION_CENTRAL, EDICION_CANAL)):
        campos = set(lector_app.MODELO[tipo])
        repetidos = set(central) & set(canal)
        if repetidos or set(central) | set(canal) != campos:
            raise AssertionError(f"particion.py no cubre el modelo de {tipo}: sobran o faltan "
                                 f"{sorted((set(central) | set(canal)) ^ campos)}, repetidos {sorted(repetidos)}")


_comprobar_modelo()


def id_valido(texto) -> bool:
    return (isinstance(texto, str) and ID_VALIDO.fullmatch(texto) is not None and ".." not in texto
            and texto.split(".", 1)[0].lower() not in RESERVADOS_WINDOWS)


def _ids(lista, donde: str) -> list:
    vistos, plegados = [], set()
    for elemento in lista:
        ident = elemento.get("id") if isinstance(elemento, dict) else None
        if not id_valido(ident):
            raise ErrorParticion(f"{donde}: el id {json.dumps(ident, ensure_ascii=False)[:80]} no vale como nombre de "
                                 "archivo (letras, números, `.`, `_` y `-`; hasta 100; ni `..` ni nombres de Windows).")
        if ident.lower() in plegados:
            raise ErrorParticion(f"{donde}: el id «{ident}» está repetido (o solo cambia en mayúsculas).")
        plegados.add(ident.lower())
        vistos.append(ident)
    return vistos


def _solo(objeto: dict, campos) -> dict:
    return {k: objeto[k] for k in campos if k in objeto}


def _desconocidos(objeto: dict, campos, donde: str):
    sobran = [k for k in objeto if k not in campos]
    if sobran:
        raise ErrorParticion(f"{donde}: campos que no son del modelo de la app: {', '.join(sobran[:10])}.")


def texto_json(valor) -> bytes:
    """Cómo se escriben los archivos sueltos: dos espacios por nivel, UTF-8 sin escapar y salto de línea al final."""
    return (json.dumps(valor, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def partir(catalogo: dict, canal: str = CANAL_OFICIAL) -> dict:
    """{ruta: bytes} con los archivos sueltos de un catálogo de esquema 1. `versionCatalogo` no va a ningún sitio: la
    pone `juntar` (sale del `catalogo.json` de `main`, que es lo que hay que hacer crecer)."""
    if not isinstance(catalogo, dict) or catalogo.get("esquema") != 1:
        raise ErrorParticion("El catálogo no es de esquema 1.")
    _desconocidos(catalogo, lector_app.MODELO["Catalogo"], "catálogo")
    juegos = catalogo.get("juegos") or []
    if len(juegos) > TOPE_JUEGOS:
        raise ErrorParticion(f"El catálogo tiene {len(juegos)} juegos; el tope es {TOPE_JUEGOS}.")
    _ids(juegos, "juegos")
    archivos = {
        RUTA_ETIQUETAS: texto_json({"esquema": 1, "etiquetas": catalogo.get("etiquetas") or []}),
        RUTA_PARCHEADOR: texto_json({"esquema": 1, **_solo(catalogo, ("launcher", "grupo"))}),
    }
    for juego in juegos:
        ident = juego["id"]
        _desconocidos(juego, lector_app.MODELO["Juego"], f"juego «{ident}»")
        ediciones = juego.get("ediciones") or []
        if len(ediciones) > TOPE_EDICIONES:
            raise ErrorParticion(f"juego «{ident}»: {len(ediciones)} ediciones; el tope es {TOPE_EDICIONES}.")
        ids_ediciones = _ids(ediciones, f"juego «{ident}»")
        central = {"esquema": 1, **_solo(juego, JUEGO_CENTRAL), "estado": "activo", "alta": dict(ALTA_MIGRADA)}
        if "ediciones" in juego:  # sin la clave, `null` o una lista: se guarda igual, para que la vuelta sea exacta
            central["ediciones"] = None if juego["ediciones"] is None else ids_ediciones
        parche = {"esquema": 1, "juego": ident, **_solo(juego, JUEGO_CANAL), "ediciones": []}
        for edicion in ediciones:
            donde = f"juego «{ident}», edición «{edicion['id']}»"
            _desconocidos(edicion, lector_app.MODELO["Edicion"], donde)
            archivos[f"juegos/{ident}/ediciones/{edicion['id']}.json"] = texto_json(
                {"esquema": 1, **_solo(edicion, EDICION_CENTRAL), "alta": dict(ALTA_MIGRADA)})
            parche["ediciones"].append({"id": edicion["id"], **_solo(edicion, EDICION_CANAL)})
        archivos[f"juegos/{ident}/juego.json"] = texto_json(central)
        archivos[f"canales/{canal}/parches/{ident}.json"] = texto_json(parche)
    return archivos


def _leer(archivos: dict, ruta: str) -> dict:
    try:
        objeto = lector_app.leer(archivos[ruta])
    except lector_app.JsonIlegible as error:
        raise ErrorParticion(f"{ruta}: {error}") from None
    if not isinstance(objeto, dict):
        raise ErrorParticion(f"{ruta}: tiene que ser un objeto JSON.")
    return objeto


def juntar(archivos: dict, version_catalogo: int, canal: str = CANAL_OFICIAL, todos: bool = False) -> dict:
    """El catálogo de esquema 1 (solo los juegos activos con parche de `canal`) a partir de los archivos sueltos
    {ruta: bytes}. Lo que no es de `juegos/`, `canales/<canal>/parches/`, `normas/etiquetas.json` ni
    `programa/parcheador.json` no se mira. Un parche que apunta a un juego o a una edición que no existe es un error.

    Con `todos`, entran también los juegos sin parche del canal (con lo central solo) y los retirados o bloqueados:
    es el catálogo con el que el robot juzga los roles, para que ningún juego se quede fuera de las reglas."""
    catalogo = {"esquema": 1, "versionCatalogo": version_catalogo}
    programa = _leer(archivos, RUTA_PARCHEADOR) if RUTA_PARCHEADOR in archivos else {}
    for clave in ("launcher", "grupo"):
        if clave in programa:
            catalogo[clave] = programa[clave]
    prefijo = f"canales/{canal}/parches/"
    juegos = []
    rutas = {r: r for r in archivos if r.startswith(prefijo) and r.endswith(".json") and "/" not in r[len(prefijo):]}
    if todos:
        for r in archivos:
            partes = r.split("/")
            if len(partes) == 3 and partes[0] == "juegos" and partes[2] == "juego.json":
                rutas.setdefault(f"{prefijo}{partes[1]}.json", None)
    for ruta, de_verdad in sorted(rutas.items()):
        if de_verdad is None:  # `todos`: juego sin parche de este canal
            ident = ruta[len(prefijo):-len(".json")]
            parche = {}
        else:
            parche = _leer(archivos, ruta)
            ident = parche.get("juego")
            if not id_valido(ident) or ruta != f"{prefijo}{ident}.json":
                raise ErrorParticion(f"{ruta}: `juego` tiene que ser el nombre del archivo.")
        ruta_juego = f"juegos/{ident}/juego.json"
        if ruta_juego not in archivos:
            raise ErrorParticion(f"{ruta}: el juego «{ident}» no existe en `juegos/`.")
        central = _leer(archivos, ruta_juego)
        if central.get("id") != ident:
            raise ErrorParticion(f"{ruta_juego}: el `id` tiene que ser el nombre de la carpeta.")
        if central.get("estado", "activo") != "activo" and not todos:
            continue  # retirado o bloqueado: no se ofrece (las ≤0.2.x no saben de canales)
        juego = {k: central[k] for k in JUEGO_CENTRAL if k in central}
        juego.update({k: parche[k] for k in JUEGO_CANAL + JUEGO_CANAL_ENCIMA if k in parche})
        if "ediciones" in central and central["ediciones"] is not None and not isinstance(central["ediciones"], list):
            raise ErrorParticion(f"{ruta_juego}: `ediciones` tiene que ser una lista de ids.")
        orden_ediciones = central.get("ediciones") or []
        if len(orden_ediciones) > TOPE_EDICIONES:
            raise ErrorParticion(f"{ruta_juego}: {len(orden_ediciones)} ediciones; el tope es {TOPE_EDICIONES}.")
        _ids([{"id": e} for e in orden_ediciones], ruta_juego)
        ediciones_canal = parche.get("ediciones") or []
        if not isinstance(ediciones_canal, list):
            raise ErrorParticion(f"{ruta}: `ediciones` tiene que ser una lista.")
        del_canal = {e["id"]: e for e in ediciones_canal if isinstance(e, dict) and isinstance(e.get("id"), str)}
        if len(del_canal) != len(ediciones_canal):
            raise ErrorParticion(f"{ruta}: cada edición del parche es un objeto con su `id`.")
        sobran = set(del_canal) - set(orden_ediciones)
        if sobran:
            raise ErrorParticion(f"{ruta}: ediciones que el juego no tiene: {', '.join(sorted(map(str, sobran)))[:200]}.")
        if "ediciones" in central and central["ediciones"] is None:
            juego["ediciones"] = None
        elif "ediciones" in central:
            juego["ediciones"] = []
            for id_edicion in orden_ediciones:
                ruta_edicion = f"juegos/{ident}/ediciones/{id_edicion}.json"
                if ruta_edicion not in archivos:
                    raise ErrorParticion(f"{ruta_juego}: la edición «{id_edicion}» no tiene archivo.")
                edicion = _leer(archivos, ruta_edicion)
                if edicion.get("id") != id_edicion:
                    raise ErrorParticion(f"{ruta_edicion}: el `id` tiene que ser el nombre del archivo.")
                juntada = {k: edicion[k] for k in EDICION_CENTRAL if k in edicion}
                juntada.update({k: v for k, v in (del_canal.get(id_edicion) or {}).items() if k in EDICION_CANAL})
                juego["ediciones"].append(juntada)
        juegos.append(juego)
    if RUTA_ETIQUETAS in archivos:
        catalogo["etiquetas"] = _leer(archivos, RUTA_ETIQUETAS).get("etiquetas") or []
    catalogo["juegos"] = sorted(juegos, key=lambda j: (_orden(j), j["id"]))
    return catalogo


def _orden(juego) -> int:
    orden = juego.get("orden")
    return orden if isinstance(orden, int) and not isinstance(orden, bool) else 0


def mismo_catalogo(a: dict, b: dict) -> bool:
    """Lo mismo para la app: mismos datos, con los juegos en el orden en que los enseña (`orden` y luego `id`)."""
    def canonico(c):
        c = dict(c)
        for clave in ("juegos", "etiquetas"):  # sin la clave o `null`: la app lo lee como una lista vacía
            c[clave] = c.get(clave) or []
        c["juegos"] = sorted(c["juegos"], key=lambda j: (_orden(j), j.get("id", "")))
        return c
    return canonico(a) == canonico(b)


def main(argv=None) -> int:
    """`python -B robot/particion.py partir <carpeta del repositorio>` (sin `-I`: con él, Python no pone `robot/` en sys.path): escribe los archivos sueltos a partir de
    `catalogo/catalogo.json` y comprueba la ida y vuelta antes de escribir nada."""
    import pathlib
    import sys
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2 or argv[0] != "partir":
        print(main.__doc__, file=sys.stderr)
        return 2
    raiz = pathlib.Path(argv[1])
    original = lector_app.leer((raiz / RUTA_CATALOGO).read_bytes())
    archivos = partir(original)
    vuelta = juntar(archivos, original["versionCatalogo"])
    if not mismo_catalogo(original, vuelta):
        print("La ida y vuelta no da el mismo catálogo: no se escribe nada.", file=sys.stderr)
        return 1
    existentes = [r for r in archivos if (raiz / r).exists()]
    if existentes:
        print(f"Ya existen: {', '.join(existentes[:10])}. No se pisa nada.", file=sys.stderr)
        return 1
    for ruta, datos in archivos.items():
        destino = raiz / ruta
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(datos)
    print(f"{len(archivos)} archivos escritos; la ida y vuelta da el mismo catálogo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
