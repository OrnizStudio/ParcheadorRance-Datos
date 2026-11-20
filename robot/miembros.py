#!/usr/bin/env python3
"""Aplica en la organización lo que dice `equipo/miembros.json` (los miembros del equipo y sus roles).

Se ejecuta después de fusionar una propuesta que toca ese archivo (trabajo `miembros` del flujo
«Robot de permisos»). Las reglas de quién puede cambiar a quién NO están aquí: las comprueba
`robot/permisos.py` antes de fusionar. Esto solo deja la organización igual que el archivo:

  - quien está en `miembros` queda en el equipo de su rol (`administradores`, `editores` o
    `colaboradores`); si aún no es de la organización, GitHub le manda la invitación;
  - quien cambia de rol pasa a su equipo nuevo y sale del anterior;
  - quien ya no está en `miembros` (y estaba en alguno de los tres equipos, o invitado) sale del equipo y
    de la organización;
  - quien está en `bloqueados` queda bloqueado en la organización; a quien se quita de ahí en la
    propuesta, se le desbloquea.

El Propietario (`normas/propietario.json`) no se toca nunca. Tampoco las cuentas de la organización que
no están en ninguno de los tres equipos (no las gestiona este archivo).

Es idempotente: mira cómo está la organización y solo hace lo que falta, así que se puede relanzar las
veces que haga falta («Re-run failed jobs»). Si algo falla, lo dice en la propuesta como fallo temporal.

Necesita un token con permiso sobre los miembros de la organización: el de una GitHub App instalada en
ella (`MIEMBROS_TOKEN`; ver `docs/miembros-github-app.md` del parcheador). Sin él no hace nada y avisa.

Solo usa la biblioteca estándar de Python y nunca ejecuta nada de la propuesta: lee `main`.
"""
from __future__ import annotations

import base64
import os
import pathlib
import sys
from dataclasses import dataclass, field

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from permisos import (RUTA_MIEMBROS, RUTA_PROPIETARIO, crear_api, leer_miembros,  # noqa: E402
                      leer_propietarios, resumen)

# El equipo de la organización de cada rol.
EQUIPOS = {"administrador": "administradores", "editor": "editores", "colaborador": "colaboradores"}
NOMBRE_ROL = {"administrador": "Administrador", "editor": "Editor", "colaborador": "Colaborador"}
MARCA = "<!-- robot-miembros -->"


@dataclass
class Estado:
    """Cómo está ahora la organización. Las cuentas, en minúsculas → tal como las escribe GitHub."""
    equipos: dict = field(default_factory=lambda: {e: {} for e in EQUIPOS.values()})    # miembros activos
    invitados: dict = field(default_factory=lambda: {e: {} for e in EQUIPOS.values()})  # invitación sin aceptar
    bloqueados: dict = field(default_factory=dict)

    def en(self, equipo: str) -> dict:
        return {**self.invitados[equipo], **self.equipos[equipo]}


@dataclass(frozen=True)
class Accion:
    tipo: str            # «poner», «quitar», «expulsar», «bloquear» o «desbloquear»
    cuenta: str
    equipo: str = ""
    rol: str = ""

    def texto(self) -> str:
        return {
            "poner": f"`{self.cuenta}` pasa a ser **{NOMBRE_ROL.get(self.rol, self.rol)}** (equipo `{self.equipo}`; "
                     "si no era de la organización, le llega la invitación)",
            "quitar": f"`{self.cuenta}` sale del equipo `{self.equipo}`",
            "expulsar": f"`{self.cuenta}` sale del equipo y de la organización",
            "bloquear": f"`{self.cuenta}` queda bloqueada en la organización",
            "desbloquear": f"`{self.cuenta}` deja de estar bloqueada",
        }[self.tipo]


def planificar(miembros: dict, bloqueados: dict, desbloquear: dict, estado: Estado, propietarios=frozenset()) -> list:
    """Lo que falta para que la organización quede como el archivo. Sin efectos: solo decide.

    `miembros` y `bloqueados` vienen de `leer_miembros`; `desbloquear` son las cuentas que la propuesta ha
    quitado de `bloqueados`.
    """
    acciones = []
    for cuenta_l, (cuenta, rol) in sorted(miembros.items()):
        if cuenta_l in propietarios:
            continue
        equipo = EQUIPOS[rol]
        if cuenta_l not in estado.en(equipo):
            acciones.append(Accion("poner", cuenta, equipo, rol))
        for otro in EQUIPOS.values():
            if otro != equipo and cuenta_l in estado.en(otro):
                acciones.append(Accion("quitar", estado.en(otro)[cuenta_l], otro))

    # Quien está (o está invitado) en alguno de los tres equipos y ya no figura en el archivo.
    sobran = {}
    for equipo in EQUIPOS.values():
        sobran.update(estado.en(equipo))
    for cuenta_l, cuenta in sorted(sobran.items()):
        if cuenta_l not in miembros and cuenta_l not in propietarios:
            acciones.append(Accion("expulsar", cuenta))

    for cuenta_l, cuenta in sorted(bloqueados.items()):
        if cuenta_l not in estado.bloqueados and cuenta_l not in propietarios:
            acciones.append(Accion("bloquear", cuenta))
    for cuenta_l, cuenta in sorted(desbloquear.items()):
        if cuenta_l in estado.bloqueados and cuenta_l not in bloqueados:
            acciones.append(Accion("desbloquear", cuenta))
    return acciones


def _paginas(org, ruta: str, tolerar=()):
    """Todas las páginas de una lista de la API (de 100 en 100)."""
    todo, pagina = [], 1
    while True:
        tanda = org("GET", f"{ruta}{'&' if '?' in ruta else '?'}per_page=100&page={pagina}", tolerar=tolerar)
        if not tanda:
            return todo
        todo += tanda
        if len(tanda) < 100:
            return todo
        pagina += 1


def leer_estado(org) -> Estado:
    """Pregunta a GitHub quién está en cada equipo, quién está invitado y quién está bloqueado."""
    estado = Estado()
    for equipo in EQUIPOS.values():
        for m in _paginas(org, f"/teams/{equipo}/members"):
            estado.equipos[equipo][m["login"].lower()] = m["login"]
        for i in _paginas(org, f"/teams/{equipo}/invitations"):
            if i.get("login"):
                estado.invitados[equipo][i["login"].lower()] = i["login"]
    # Sin el permiso «Blocking users» la App no ve los bloqueos (403/404): se sigue sin ellos.
    for b in _paginas(org, "/blocks", tolerar=(403, 404)):
        estado.bloqueados[b["login"].lower()] = b["login"]
    return estado


def aplicar(acciones: list, org) -> list:
    """Hace cada acción y devuelve lo hecho, en frases. Un 404 al quitar algo que ya no está no es un error."""
    hecho = []
    for a in acciones:
        if a.tipo == "poner":
            org("PUT", f"/teams/{a.equipo}/memberships/{a.cuenta}", {"role": "member"})
        elif a.tipo == "quitar":
            org("DELETE", f"/teams/{a.equipo}/memberships/{a.cuenta}", tolerar=(404,))
        elif a.tipo == "expulsar":
            org("DELETE", f"/memberships/{a.cuenta}", tolerar=(404,))
        elif a.tipo == "bloquear":
            org("PUT", f"/blocks/{a.cuenta}")
        elif a.tipo == "desbloquear":
            org("DELETE", f"/blocks/{a.cuenta}", tolerar=(404,))
        hecho.append(a.texto())
    return hecho


def comentar(api, numero, texto: str) -> None:
    """Un único comentario de este trabajo por propuesta (aparte del de permisos), que se va actualizando."""
    if not numero:
        return
    cuerpo = f"{MARCA}\n{texto}"
    comentarios = api("GET", f"/issues/{numero}/comments?per_page=100") or []
    propio = next((c for c in comentarios if MARCA in (c.get("body") or "")), None)
    if propio:
        api("PATCH", f"/issues/comments/{propio['id']}", {"body": cuerpo})
    else:
        api("POST", f"/issues/{numero}/comments", {"body": cuerpo})


AVISO_SIN_TOKEN = (
    "### ⚠️ Cambios de miembros guardados, pero sin aplicar en la organización\n\n"
    "El archivo `equipo/miembros.json` ya está publicado, pero el robot no tiene con qué aplicarlo: faltan los "
    "secretos `MIEMBROS_APP_ID` y `MIEMBROS_APP_CLAVE` de la GitHub App (o la App no está instalada en la "
    "organización). **No es un rechazo ni un error de la propuesta.**\n\n"
    "Cuando el Propietario los ponga (pasos en `docs/miembros-github-app.md` del parcheador), basta con "
    "relanzar este trabajo («Re-run failed jobs» o «Run workflow»): es idempotente.")


def aviso_fallo(error) -> str:
    return ("### ⏳ Fallo temporal al aplicar los cambios de miembros (no es un rechazo)\n\n"
            "La propuesta está publicada, pero al aplicarla en la organización algo ha fallado:\n\n"
            f"> {str(error)[:600]}\n\n"
            "Lo que ya se hubiera hecho, hecho está. Para terminar: en la pestaña «Checks», «Re-run failed "
            "jobs» (el trabajo es idempotente: solo hace lo que falta).")


def main() -> int:
    repositorio = os.environ["GITHUB_REPOSITORY"]
    organizacion = repositorio.split("/")[0]
    numero = int(os.environ.get("PR_NUMERO") or 0)
    api = crear_api(repositorio, os.environ["GITHUB_TOKEN"])

    if "--fallo-token" in sys.argv[1:]:
        # Lo lanza el flujo cuando no se ha podido crear el token de la App (clave mal pegada, App sin instalar…).
        texto = aviso_fallo("No se ha podido crear el token de la GitHub App. Revisa los secretos "
                            "`MIEMBROS_APP_ID` y `MIEMBROS_APP_CLAVE` y que la App esté instalada en la organización.")
        comentar(api, numero, texto)
        resumen(texto)
        return 1

    desbloquear = {}
    raiz = pathlib.Path(__file__).resolve().parents[1]  # la copia de `main`, nunca la propuesta
    if numero:
        propuesta = api("GET", f"/pulls/{numero}")
        if not propuesta.get("merged"):
            resumen("La propuesta no se ha publicado (borrador o sin fusionar): no hay nada que aplicar.")
            return 0
        archivos = [f.get("filename") for f in api("GET", f"/pulls/{numero}/files?per_page=100") or []]
        if RUTA_MIEMBROS not in archivos:
            resumen("La propuesta no cambia los miembros del equipo: nada que aplicar.")
            return 0
        # Lo que había antes de la propuesta, solo para saber a quién se ha quitado de `bloqueados`.
        antes = api("GET", f"/contents/{RUTA_MIEMBROS}?ref={propuesta['base']['sha']}", tolerar=(404,))
        if antes and antes.get("content"):
            _, b_antes, _ = leer_miembros(base64.b64decode(antes["content"]).decode("utf-8", errors="replace"))
            desbloquear = b_antes

    token = (os.environ.get("MIEMBROS_TOKEN") or "").strip()
    if not token:
        comentar(api, numero, AVISO_SIN_TOKEN)
        resumen(AVISO_SIN_TOKEN)
        return 0  # no rompe nada: el cambio queda guardado y se aplica cuando haya token

    try:
        archivo = raiz / RUTA_MIEMBROS
        miembros, bloqueados, errores = leer_miembros(archivo.read_text(encoding="utf-8") if archivo.exists() else None)
        if errores:
            raise RuntimeError("; ".join(errores))
        propietarios = leer_propietarios((raiz / RUTA_PROPIETARIO).read_text(encoding="utf-8"))
        api_org = crear_api(repositorio, token)

        def org(metodo, ruta, datos=None, tolerar=()):
            return api_org(metodo, f"https://api.github.com/orgs/{organizacion}{ruta}", datos, tolerar)

        desbloquear = {c: n for c, n in desbloquear.items() if c not in bloqueados}
        acciones = planificar(miembros, bloqueados, desbloquear, leer_estado(org), propietarios)
        hecho = aplicar(acciones, org)
    except (RuntimeError, OSError, ValueError) as error:
        texto = aviso_fallo(error)
        comentar(api, numero, texto)
        resumen(texto)
        return 1

    if hecho:
        texto = "### 👥 Cambios de miembros aplicados en la organización\n\n" + "\n".join(f"- {h}" for h in hecho)
    else:
        texto = "### 👥 Miembros: la organización ya estaba como dice el archivo\n\nNo había nada que cambiar."
    comentar(api, numero, texto)
    resumen(texto)
    return 0


if __name__ == "__main__":
    sys.exit(main())
