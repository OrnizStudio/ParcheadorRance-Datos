"""Pruebas de los miembros del equipo: las reglas de `equipo/miembros.json` (robot/permisos.py) y lo que se
aplica en la organización (robot/miembros.py), con la API de GitHub simulada.

    python -m unittest discover -s robot/pruebas
"""
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import miembros as m  # noqa: E402
from permisos import Cambio, Permisos, Rol, RUTA_MIEMBROS, comprobar, comprobar_miembros, leer_miembros  # noqa: E402

PROPIETARIOS = frozenset({"ana"})


def archivo(miembros: dict, bloqueados=()):
    return json.dumps({"esquema": 1, "miembros": [{"cuenta": c, "rol": r} for c, r in miembros.items()],
                       "bloqueados": list(bloqueados)})


BASE = {"marta": "administrador", "luis": "editor", "sara": "colaborador"}


class ReglasDeMiembros(unittest.TestCase):
    def motivos(self, despues, quien="ana", rol=Rol.PROPIETARIO, antes=None, otros=None):
        quienes = {quien: rol, **(otros or {})}
        return comprobar_miembros(archivo(BASE) if antes is None else antes, despues, quienes, PROPIETARIOS)

    # ── El Propietario, a todos.
    def test_el_propietario_pone_quita_y_cambia_a_cualquiera(self):
        self.assertEqual([], self.motivos(archivo({"marta": "editor", "luis": "administrador", "pepe": "administrador"})))

    def test_el_propietario_bloquea_y_desbloquea(self):
        self.assertEqual([], self.motivos(archivo(BASE, ["spam"])))
        self.assertEqual([], self.motivos(archivo(BASE), antes=archivo(BASE, ["spam"])))

    # ── El Administrador, solo a Editores y Colaboradores.
    def test_un_administrador_gestiona_editores_y_colaboradores(self):
        despues = archivo({"marta": "administrador", "luis": "colaborador", "pepe": "editor"})  # luis baja, sara fuera, pepe entra
        self.assertEqual([], self.motivos(despues, "marta", Rol.ADMINISTRADOR))

    def test_un_administrador_no_toca_a_otro_administrador(self):
        antes = archivo({**BASE, "otro": "administrador"})
        for despues in (archivo(BASE),                                   # lo quita
                        archivo({**BASE, "otro": "editor"})):          # lo baja
            motivos = self.motivos(despues, "marta", Rol.ADMINISTRADOR, antes=antes)
            self.assertEqual(1, len(motivos), motivos)
            self.assertIn("solo del Propietario", motivos[0])

    def test_un_administrador_no_nombra_administradores(self):
        motivos = self.motivos(archivo({**BASE, "pepe": "administrador"}), "marta", Rol.ADMINISTRADOR)
        self.assertIn("`pepe`: poner, quitar o cambiar a un Administrador es solo del Propietario", motivos[0])
        motivos = self.motivos(archivo({**BASE, "luis": "administrador"}), "marta", Rol.ADMINISTRADOR)
        self.assertIn("`luis`", motivos[0])

    def test_un_administrador_no_se_quita_ni_se_cambia_a_si_mismo(self):
        motivos = self.motivos(archivo({"luis": "editor", "sara": "colaborador"}), "marta", Rol.ADMINISTRADOR)
        self.assertIn("`marta`", motivos[0])

    def test_un_administrador_no_bloquea(self):
        motivos = self.motivos(archivo(BASE, ["spam"]), "marta", Rol.ADMINISTRADOR)
        self.assertEqual(["`bloqueados`: bloquear o desbloquear cuentas es solo del Propietario."], motivos)

    # ── Los demás, a nadie.
    def test_un_editor_o_un_colaborador_no_gestionan_a_nadie(self):
        for quien, rol in (("luis", Rol.EDITOR), ("sara", Rol.COLABORADOR), ("nadie", Rol.NINGUNO)):
            motivos = self.motivos(archivo({**BASE, "pepe": "colaborador"}), quien, rol)
            self.assertEqual(1, len(motivos))
            self.assertIn("los gestionan los Administradores y el Propietario", motivos[0])

    # ── Nadie se sube a sí mismo.
    def test_nadie_se_sube_a_si_mismo_de_rol(self):
        # Aunque GitHub le diera nivel de Administrador, si en el archivo es Editor no se sube solo…
        motivos = self.motivos(archivo({**BASE, "luis": "administrador"}), "luis", Rol.PROPIETARIO)
        self.assertTrue(any("nadie se sube a sí mismo de rol" in x for x in motivos), motivos)
        # …ni se mete él mismo en el equipo.
        motivos = self.motivos(archivo({**BASE, "pepe": "editor"}), "pepe", Rol.PROPIETARIO)
        self.assertTrue(any("`pepe`: nadie se sube a sí mismo" in x for x in motivos), motivos)

    def test_cuenta_el_rol_mas_bajo_de_quienes_hacen_la_propuesta(self):
        # El Propietario la abre, pero el último cambio lo sube un Editor: manda el Editor.
        motivos = self.motivos(archivo({**BASE, "pepe": "editor"}), "ana", Rol.PROPIETARIO, otros={"luis": Rol.EDITOR})
        self.assertIn("tu rol: Editor", motivos[0])

    # ── El Propietario no va en el archivo, y el archivo tiene que estar bien escrito.
    def test_el_propietario_no_va_en_el_archivo(self):
        motivos = self.motivos(archivo({**BASE, "Ana": "colaborador"}))
        self.assertIn("es el Propietario", motivos[0])
        self.assertIn("es el Propietario", self.motivos(archivo(BASE, ["ana"]))[0])

    def test_el_archivo_tiene_que_estar_bien_escrito(self):
        self.assertIn("no es un JSON válido", self.motivos("{ esto no")[0])
        self.assertIn("rol que no existe", self.motivos(archivo({"pepe": "jefe"}))[0])
        self.assertIn("no es una cuenta de GitHub válida", self.motivos(archivo({"pe pe": "editor"}))[0])
        self.assertIn("no puede ser miembro y estar bloqueada", self.motivos(archivo(BASE, ["luis"]))[0])
        repetida = json.dumps({"miembros": [{"cuenta": "Luis", "rol": "editor"}, {"cuenta": "luis", "rol": "colaborador"}]})
        self.assertIn("está repetida", self.motivos(repetida)[0])
        self.assertIn("No se puede borrar", self.motivos(None)[0])

    def test_sin_archivo_todavia_el_propietario_lo_crea(self):
        self.assertEqual([], comprobar_miembros(None, archivo({"luis": "editor"}), {"ana": Rol.PROPIETARIO}, PROPIETARIOS))

    # ── Los archivos: `equipo/miembros.json` lo deciden estas reglas; en `equipo/` no va nada más.
    def test_en_la_carpeta_equipo_solo_va_miembros_json(self):
        catalogo = json.dumps({"esquema": 1, "versionCatalogo": 1, "juegos": []})
        admin = Permisos(Rol.ADMINISTRADOR)
        self.assertEqual([], comprobar([Cambio(RUTA_MIEMBROS, "M")], catalogo, catalogo, admin))
        motivos = comprobar([Cambio("equipo/otro.json", "A")], catalogo, catalogo, admin)
        self.assertIn("solo va `equipo/miembros.json`", motivos[0])

    def test_leer_miembros(self):
        miembros, bloqueados, errores = leer_miembros(archivo({"Luis": "editor"}, ["Spam"]))
        self.assertEqual(({"luis": ("Luis", "editor")}, {"spam": "Spam"}, []), (miembros, bloqueados, errores))
        self.assertEqual(({}, {}, []), leer_miembros(None))


class ApiFalsa:
    """La parte de la API de la organización que usa `robot/miembros.py`, en memoria."""

    def __init__(self, equipos=None, invitados=None, bloqueados=(), falla=None, sin_bloqueos=False):
        self.equipos = {e: list((equipos or {}).get(e, [])) for e in m.EQUIPOS.values()}
        self.invitados = {e: list((invitados or {}).get(e, [])) for e in m.EQUIPOS.values()}
        self.bloqueados = list(bloqueados)
        self.falla = falla
        self.sin_bloqueos = sin_bloqueos
        self.escrituras = []

    def __call__(self, metodo, ruta, datos=None, tolerar=()):
        ruta_sola = ruta.split("?")[0]
        partes = ruta_sola.strip("/").split("/")
        if metodo != "GET":
            self.escrituras.append(f"{metodo} {ruta_sola}")
            if self.falla and self.falla in ruta_sola:
                raise RuntimeError(f"GitHub respondió 502 a {metodo} {ruta_sola}")
        if metodo == "GET" and partes[0] == "teams":
            lista = self.equipos[partes[1]] if partes[2] == "members" else self.invitados[partes[1]]
            return [{"login": c} for c in lista] if "page=1" in ruta else []
        if metodo == "GET" and partes[0] == "blocks":
            if self.sin_bloqueos:
                return None if 403 in tolerar else self._error(403)
            return [{"login": c} for c in self.bloqueados] if "page=1" in ruta else []
        cuenta = partes[-1]
        if partes[0] == "teams" and metodo == "PUT":
            # Quien no es de la organización queda invitado; quien ya lo es, dentro.
            de_la_org = any(cuenta in e for e in self.equipos.values())
            (self.equipos if de_la_org else self.invitados)[partes[1]].append(cuenta)
            return {"state": "active" if de_la_org else "pending"}
        if partes[0] == "teams" and metodo == "DELETE":
            for lista in (self.equipos[partes[1]], self.invitados[partes[1]]):
                if cuenta in lista:
                    lista.remove(cuenta)
            return {}
        if partes[0] == "memberships" and metodo == "DELETE":
            for grupo in (self.equipos, self.invitados):
                for lista in grupo.values():
                    if cuenta in lista:
                        lista.remove(cuenta)
            return {}
        if partes[0] == "blocks":
            if metodo == "PUT":
                self.bloqueados.append(cuenta)
            elif cuenta in self.bloqueados:
                self.bloqueados.remove(cuenta)
            return {}
        raise AssertionError(f"La API falsa no conoce {metodo} {ruta}")

    @staticmethod
    def _error(codigo):
        raise RuntimeError(f"GitHub respondió {codigo}")


class AplicarEnLaOrganizacion(unittest.TestCase):
    def sincronizar(self, api, miembros, bloqueados=(), desbloquear=()):
        m_, b_, errores = leer_miembros(archivo(miembros, bloqueados))
        self.assertEqual([], errores)
        acciones = m.planificar(m_, b_, {c.lower(): c for c in desbloquear}, m.leer_estado(api), PROPIETARIOS)
        return m.aplicar(acciones, api)

    def test_invita_mueve_quita_y_expulsa(self):
        api = ApiFalsa(equipos={"administradores": ["ana", "marta"], "editores": ["ana", "luis"], "colaboradores": ["ana", "sara"]})
        # luis baja a Colaborador, sara sale, pepe entra de Editor; marta sigue igual.
        hecho = self.sincronizar(api, {"marta": "administrador", "luis": "colaborador", "pepe": "editor"})

        self.assertEqual(
            ["PUT /teams/colaboradores/memberships/luis", "DELETE /teams/editores/memberships/luis",
             "PUT /teams/editores/memberships/pepe", "DELETE /memberships/sara"], api.escrituras)
        self.assertEqual(["ana", "marta"], api.equipos["administradores"])       # al Propietario no se le toca
        self.assertEqual(["ana", "luis"], api.equipos["colaboradores"])
        self.assertEqual(["ana"], api.equipos["editores"])
        self.assertEqual(["pepe"], api.invitados["editores"])                    # no era de la organización: invitado
        self.assertEqual(4, len(hecho))
        self.assertIn("`pepe` pasa a ser **Editor**", hecho[2])

    def test_es_idempotente(self):
        api = ApiFalsa(equipos={"administradores": ["ana"], "editores": ["ana", "luis"], "colaboradores": ["ana"]})
        deseado = {"luis": "colaborador", "pepe": "editor"}
        self.assertEqual(3, len(self.sincronizar(api, deseado)))
        antes = list(api.escrituras)
        # La segunda vez no hay nada que hacer: tampoco se vuelve a invitar a quien ya está invitado.
        self.assertEqual([], self.sincronizar(api, deseado))
        self.assertEqual(antes, api.escrituras)

    def test_si_se_corta_a_medias_al_relanzar_termina_lo_que_faltaba(self):
        api = ApiFalsa(equipos={"administradores": ["ana"], "editores": ["ana", "luis"], "colaboradores": ["ana", "sara"]},
                       falla="/memberships/sara")
        with self.assertRaises(RuntimeError):
            self.sincronizar(api, {"luis": "colaborador"})
        self.assertEqual(["ana", "sara", "luis"], api.equipos["colaboradores"])  # lo de luis sí se hizo; sara sigue
        self.assertEqual(["ana"], api.equipos["editores"])
        api.falla = None
        api.escrituras.clear()
        self.sincronizar(api, {"luis": "colaborador"})
        self.assertEqual(["DELETE /memberships/sara"], api.escrituras)             # solo lo que faltaba

    def test_cancela_la_invitacion_de_quien_se_quita_antes_de_aceptar(self):
        api = ApiFalsa(equipos={"administradores": ["ana"]}, invitados={"editores": ["pepe"]})
        self.sincronizar(api, {})
        self.assertEqual(["DELETE /memberships/pepe"], api.escrituras)

    def test_no_toca_a_quien_no_esta_en_ninguno_de_los_tres_equipos(self):
        # Una cuenta de la organización fuera de los tres equipos (un bot, p. ej.) no la gestiona el archivo.
        api = ApiFalsa(equipos={"administradores": ["ana"]})
        self.assertEqual([], self.sincronizar(api, {}))
        self.assertEqual([], api.escrituras)

    def test_bloquea_y_desbloquea(self):
        api = ApiFalsa(equipos={"administradores": ["ana"]}, bloqueados=["viejo", "otro"])
        self.sincronizar(api, {}, bloqueados=["spam", "otro"], desbloquear=["viejo"])
        self.assertEqual(["PUT /blocks/spam", "DELETE /blocks/viejo"], api.escrituras)
        # Un bloqueo que nadie ha quitado en la propuesta se queda, aunque no esté en el archivo.
        api.escrituras.clear()
        self.sincronizar(ApiFalsa(bloqueados=["a-mano"]), {})
        self.assertEqual([], api.escrituras)

    def test_sin_permiso_para_ver_los_bloqueos_lo_demas_sigue(self):
        api = ApiFalsa(equipos={"administradores": ["ana"], "editores": ["ana"]}, sin_bloqueos=True)
        self.sincronizar(api, {"pepe": "editor"})
        self.assertEqual(["PUT /teams/editores/memberships/pepe"], api.escrituras)

    def test_los_avisos_dicen_que_no_es_un_rechazo(self):
        self.assertIn("⏳", m.aviso_fallo("GitHub respondió 502"))
        self.assertIn("no es un rechazo", m.aviso_fallo("x"))
        self.assertIn("No es un rechazo", m.AVISO_SIN_TOKEN)
        self.assertNotIn("❌", m.AVISO_SIN_TOKEN + m.aviso_fallo("x"))


if __name__ == "__main__":
    unittest.main()
