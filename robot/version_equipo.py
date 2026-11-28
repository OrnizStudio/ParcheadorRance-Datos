"""La versión mínima del Modo equipo (docs/canales.md §8.1).

El Dueño del programa pone en `programa/parcheador.json` (`launcher.versionMinimaEquipo`) desde qué versión del
parcheador se puede editar. El parcheador escribe al final de cada propuesta que abre `<!-- parcheador: X.Y.Z -->`, y
el robot rechaza la de alguien que no es el Dueño si no lleva esa marca o si es de una versión anterior. Es una red de
seguridad para que nadie edite con un Equipo viejo (que no conoce reglas nuevas), no una barrera: la marca se puede
escribir a mano. Sin `versionMinimaEquipo` (o vacía, o mal escrita) no se mira nada.

Las versiones se leen y se comparan como `VersionLauncher` de la app: de 1 a 4 números, `v` inicial opcional, parte
previa (`1.2.0-beta.2`, menor que la final) y metadatos (`+abc`) que no cuentan.
"""

from __future__ import annotations

import json
import re

RUTA_PARCHEADOR = "programa/parcheador.json"

# La marca que deja el parcheador; vale la última (la app la pone al final del cuerpo).
MARCA = re.compile(r"<!--\s*parcheador:\s*([^\s<>]{1,64})\s*-->")

# Un cuerpo de propuesta de GitHub no pasa de 65 536 caracteres: con más, no se busca nada.
TOPE_CUERPO = 70_000

_MAX_INT = 2 ** 31 - 1


def leer_version(texto):
    """(números, partes previas) o None si no es una versión."""
    if not isinstance(texto, str) or not texto.strip():
        return None
    limpio = texto.strip()
    if limpio[0] in "vV":
        limpio = limpio[1:]
    limpio = limpio.split("+", 1)[0]
    numeros, guion, previa = limpio.partition("-")
    trozos = numeros.split(".")
    if not 1 <= len(trozos) <= 4 or not all(t and t.isascii() and t.isdigit() for t in trozos):
        return None
    valores = [int(t) for t in trozos]
    if any(v > _MAX_INT for v in valores):
        return None
    partes = previa.split(".") if guion else []
    for parte in partes:
        if not parte or not all(c.isascii() and (c.isalnum() or c == "-") for c in parte):
            return None
    return valores, partes


def _trozo(a: str, b: str) -> int:
    a_num, b_num = a.isdigit(), b.isdigit()
    if a_num and b_num:
        a, b = a.lstrip("0"), b.lstrip("0")
        if len(a) != len(b):
            return -1 if len(a) < len(b) else 1
    elif a_num:
        return -1
    elif b_num:
        return 1
    return (a > b) - (a < b)


def comparar(a, b) -> int:
    """<0, 0 o >0, como `VersionLauncher.CompareTo`."""
    (na, pa), (nb, pb) = a, b
    for i in range(max(len(na), len(nb))):
        x = na[i] if i < len(na) else 0
        y = nb[i] if i < len(nb) else 0
        if x != y:
            return -1 if x < y else 1
    if not pa or not pb:
        return (len(pb) > len(pa)) - (len(pb) < len(pa))
    for x, y in zip(pa, pb):
        if r := _trozo(x, y):
            return r
    return (len(pa) > len(pb)) - (len(pa) < len(pb))


def minima(texto_parcheador, texto_catalogo):
    """El texto de `launcher.versionMinimaEquipo` de `main` si es una versión, o None. Se mira `programa/parcheador.json`
    y, si aún no existe (antes de la migración), `catalogo/catalogo.json`."""
    for texto in (texto_parcheador, texto_catalogo):
        if texto is None:
            continue
        try:
            datos = json.loads(texto)
        except (ValueError, TypeError, RecursionError):
            return None
        launcher = datos.get("launcher") if isinstance(datos, dict) else None
        valor = launcher.get("versionMinimaEquipo") if isinstance(launcher, dict) else None
        return valor.strip() if isinstance(valor, str) and leer_version(valor) is not None else None
    return None


def version_de(cuerpo):
    """La versión de la última marca `<!-- parcheador: … -->` del cuerpo (el texto tal cual), o None."""
    if not isinstance(cuerpo, str) or len(cuerpo) > TOPE_CUERPO:
        return None
    marcas = MARCA.findall(cuerpo)
    return marcas[-1] if marcas else None


def motivo(texto_parcheador, texto_catalogo, cuerpo):
    """Por qué no se acepta una propuesta de un Equipo viejo, o None si vale (o no hay versión mínima)."""
    texto_minima = minima(texto_parcheador, texto_catalogo)
    if texto_minima is None:
        return None
    exigida = leer_version(texto_minima)
    marca = version_de(cuerpo)
    usada = leer_version(marca) if marca is not None else None
    if usada is None:
        return (f"Esta propuesta no dice con qué parcheador se hizo: para editar en el Modo equipo hace falta la "
                f"v{texto_minima} o posterior. Actualiza el parcheador y envía el cambio desde él.")
    if comparar(usada, exigida) < 0:
        return (f"Esta propuesta se hizo con el parcheador v{marca.lstrip('vV')}: para editar en el Modo equipo hace "
                f"falta la v{texto_minima} o posterior. Actualiza el parcheador y vuelve a enviar el cambio.")
    return None
