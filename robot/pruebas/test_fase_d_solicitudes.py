"""Fase D, entrega 3: las solicitudes (`robot/solicitudes.py`, integrado en `permisos.comprobar` y `permisos.main`).

Un canal nuevo lo pide cualquiera con una propuesta que solo añade su `canal.json` y su `miembros.json`; la aprueba el
Dueño con la etiqueta `aprobada`, en el evento `labeled`. La verificación la pide el Propietario con un archivo en
`solicitudes/verificacion/`.
"""

import datetime
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import particion  # noqa: E402
import solicitudes  # noqa: E402
from permisos import Cambio, Permisos, Rol, comprobar  # noqa: E402
from test_fase_d_canales import OTRO, PARCHE_ES, canal_json, main_con_dos_canales  # noqa: E402
from test_fase_d_listas import DUENO, canales_bloqueados, huellas, usuarios, veto  # noqa: E402
from test_sueltos import CATALOGO, HOY, YO, Propuesta  # noqa: E402

NUEVO = "rance_fr"
CANAL_NUEVO = f"canales/{NUEVO}/canal.json"
MIEMBROS_NUEVO = f"canales/{NUEVO}/miembros.json"
VERIFICACION_ES = f"solicitudes/verificacion/{OTRO}.json"
HASH_MALO = "blake3:" + "e" * 64
OTRA = 9191


def miembro(cuenta_id=YO, cuenta="yo", rol="propietario", estado="activo"):
    return {"id": cuenta_id, "cuenta": cuenta, "rol": rol, "desde": HOY.isoformat(), "estado": estado}


def nuevo_canal(main=None, canal=NUEVO, nombre="Traductores Galos", miembros=None, **campos):
    p = Propuesta(main or main_con_dos_canales())
    objeto = canal_json(canal, nombre, paquetes=("galos/parches",))
    objeto.update({"creado": HOY.isoformat(), **campos})
    p.poner(f"canales/{canal}/canal.json", objeto)
    p.poner(f"canales/{canal}/miembros.json", {"esquema": 1, "miembros": miembros or [miembro()]})
    return p


def juzgar(p, permisos=None, creada=datetime.date(2025, 1, 1), abiertas=0, login="yo", cambios=None):
    texto = particion.texto_json(CATALOGO).decode("utf-8")
    lados = {"antes": p.antes, "despues": p.despues}
    return comprobar(cambios or p.cambios(), texto, texto.encode(),
                     permisos or Permisos(Rol.NINGUNO, cuenta_id=YO),
                     leer_archivo=lambda ruta, lado: lados[lado].get(ruta), leer_sueltos=lambda lado: lados[lado],
                     hoy=HOY, ids_duenos=frozenset({DUENO}), cuenta_de=lambda i: login if i == YO else f"c{i}",
                     creada_el=lambda i: creada, solicitudes_abiertas=lambda etiqueta: abiertas)


def hay(motivos, texto):
    return any(texto in m for m in motivos)


class Clasificar(unittest.TestCase):
    def test_canal_nuevo(self):
        p = nuevo_canal()
        sol = solicitudes.clasificar([(c.ruta, c.estado) for c in p.cambios()], lambda r: r in p.antes)
        self.assertEqual(solicitudes.Solicitud("canal", NUEVO), sol)
        self.assertEqual("solicitud:canal", sol.etiqueta)
        self.assertTrue(sol.necesita_aprobacion)

    def test_verificacion(self):
        sol = solicitudes.clasificar([(VERIFICACION_ES, "A")], lambda r: False)
        self.assertEqual(solicitudes.Solicitud("verificacion", OTRO), sol)
        self.assertFalse(sol.necesita_aprobacion)

    def test_lo_demas_no_es_una_solicitud(self):
        self.assertIsNone(solicitudes.clasificar([(PARCHE_ES, "M")], lambda r: True))

    def test_una_solicitud_va_sola(self):
        for cambios in ([(VERIFICACION_ES, "A"), (PARCHE_ES, "M")], [(VERIFICACION_ES, "D")],
                        [("solicitudes/otra.json", "A")], [("solicitudes/verificacion/../x.json", "A")]):
            with self.subTest(cambios=cambios), self.assertRaises(ValueError):
                solicitudes.clasificar(cambios, lambda r: False)

    def test_un_canal_con_algo_mas_no_es_una_solicitud(self):
        # Se juzga con las reglas de siempre, que no dejan crear canales.
        for cambios in ([(CANAL_NUEVO, "A"), (MIEMBROS_NUEVO, "A"), (PARCHE_ES, "M")],
                        [(CANAL_NUEVO, "A"), (MIEMBROS_NUEVO, "A"), (f"canales/{NUEVO}/logo.png", "A")],
                        [(CANAL_NUEVO, "A"), (MIEMBROS_NUEVO, "A"), ("canales/otro_mas/canal.json", "A"),
                         ("canales/otro_mas/miembros.json", "A")],
                        [(CANAL_NUEVO, "A")], [("canales/Raro/canal.json", "A"), ("canales/Raro/miembros.json", "A")]):
            with self.subTest(cambios=cambios):
                self.assertIsNone(solicitudes.clasificar(cambios, lambda r: False))


class CanalNuevo(unittest.TestCase):
    def test_bien_formada_queda_para_el_dueno(self):
        # Sin motivos: `main()` la etiqueta y espera a `aprobada`.
        self.assertEqual([], juzgar(nuevo_canal()))

    def test_mezclada_con_otro_cambio(self):
        p = nuevo_canal().cambiar(PARCHE_ES, lambda q: q["ediciones"][0].update(notaEdicion="x"))
        self.assertTrue(juzgar(p))

    def test_cuenta_de_menos_de_30_dias(self):
        self.assertTrue(hay(juzgar(nuevo_canal(), creada=HOY - datetime.timedelta(days=29)), "30 días"))
        self.assertEqual([], juzgar(nuevo_canal(), creada=HOY - datetime.timedelta(days=30)))
        self.assertTrue(hay(juzgar(nuevo_canal(), creada=None), "30 días"))

    def test_tres_abiertas_como_mucho(self):
        self.assertEqual([], juzgar(nuevo_canal(), abiertas=2))
        self.assertTrue(hay(juzgar(nuevo_canal(), abiertas=3), "3 solicitudes"))
        self.assertTrue(hay(juzgar(nuevo_canal(), abiertas=5000), "3 solicitudes"))

    def test_un_arroba_que_se_parece_a_otro_canal(self):
        for arroba in ("ornizen_", "rance_e5", "orniz", "o_r_n_i_z_e_n"):
            with self.subTest(arroba=arroba):
                self.assertTrue(juzgar(nuevo_canal(canal=arroba)), arroba)

    def test_un_nombre_con_homoglifos(self):
        # «Е» cirílica y «ѕ» cirílica: se ve igual que el nombre de @rance_es.
        self.assertTrue(juzgar(nuevo_canal(nombre="Rance en Еѕpañol")))
        self.assertTrue(juzgar(nuevo_canal(nombre="0rnizen")))

    def test_programa_esta_reservado(self):
        self.assertTrue(hay(juzgar(nuevo_canal(canal="programa", nombre="Programa")), "reservado por el programa"))

    def test_un_arroba_que_ya_existio(self):
        main = main_con_dos_canales()
        canal = canal_json()
        canal["idAnteriores"] = [{"id": NUEVO, "hasta": "2026-11-01"}]
        main[f"canales/{OTRO}/canal.json"] = particion.texto_json(canal)
        self.assertTrue(juzgar(nuevo_canal(main)))

    def test_un_canal_bloqueado_no_se_vuelve_a_pedir(self):
        main = main_con_dos_canales()
        main.update(canales_bloqueados(NUEVO))
        self.assertTrue(hay(juzgar(nuevo_canal(main)), "bloqueado"))

    def test_un_vetado_no_pide_canales(self):
        main = main_con_dos_canales()
        main.update(usuarios(veto(YO, "Spam")))
        self.assertTrue(hay(juzgar(nuevo_canal(main)), "lista negra del programa"))

    def test_quien_pide_es_el_unico_propietario(self):
        casos = {
            "otro propietario": [miembro(OTRA, "otra")],
            "otro de más": [miembro(), miembro(OTRA, "otra", "editor")],
            "invitado": [miembro(estado="invitado"), miembro(OTRA, "otra")],
            "editor": [miembro(rol="editor"), miembro(OTRA, "otra")],
        }
        for caso, filas in casos.items():
            with self.subTest(caso=caso):
                self.assertTrue(hay(juzgar(nuevo_canal(miembros=filas)), "un solo miembro"))

    def test_la_cuenta_con_su_nombre_actual(self):
        self.assertTrue(hay(juzgar(nuevo_canal(), login="otro_nombre"), "nombre actual"))

    def test_varias_cuentas_no_piden_canales(self):
        self.assertTrue(hay(juzgar(nuevo_canal(), Permisos(Rol.NINGUNO)), "una sola cuenta"))

    def test_no_se_pide_verificado_ni_oculto_ni_retirado(self):
        verificado = canal_json(NUEVO, "Traductores Galos", verificado=True)["verificacion"]
        for campos, texto in (({"verificacion": verificado}, "verificación"), ({"oculto": True}, "sin ocultar"),
                              ({"estado": "retirado"}, "activo"), ({"idAnteriores": [{"id": "galos", "hasta": "2026-11-01"}]}, "anteriores"),
                              ({"creado": "2020-01-01"}, "fecha de hoy")):
            with self.subTest(campos=campos):
                self.assertTrue(hay(juzgar(nuevo_canal(**campos)), texto), campos)

    def test_las_normas_vigentes(self):
        main = main_con_dos_canales()
        main[solicitudes.RUTA_NORMAS] = particion.texto_json({"esquema": 1, "version": 3})
        self.assertTrue(hay(juzgar(nuevo_canal(main)), "versión 3"))
        self.assertEqual([], juzgar(nuevo_canal(main, normasAceptadas=3)))
        main[solicitudes.RUTA_NORMAS] = b"{roto"
        self.assertTrue(hay(juzgar(nuevo_canal(main, normasAceptadas=0)), "normasAceptadas"))

    def test_un_enlace_simbolico_no(self):
        p = nuevo_canal()
        cambios = [Cambio(c.ruta, c.estado, "120000" if c.ruta == CANAL_NUEVO else c.modo, c.tamano)
                   for c in p.cambios()]
        self.assertTrue(hay(juzgar(p, cambios=cambios), "archivos normales"))

    def test_el_dueno_no_hace_solicitudes(self):
        # Lo suyo no se etiqueta: se juzga como siempre (y no da el motivo de las solicitudes).
        motivos = juzgar(nuevo_canal(), Permisos(Rol.DUENO, cuenta_id=DUENO))
        self.assertFalse(hay(motivos, "30 días") or hay(motivos, "Propietario activo"), motivos)


def verificacion(**campos):
    objeto = {"esquema": 1, "canal": OTRO, "motivo": "Somos el grupo de traducción de siempre.", "pedidaPor": YO,
              "fecha": HOY.isoformat()}
    objeto.update(campos)
    return {k: v for k, v in objeto.items() if v is not None}


def main_para_verificar(miembros=2, enlace=True, estado_version="publico", hash_version=None, retirada="2026-11-01"):
    main = main_con_dos_canales()
    canal = canal_json()
    if enlace:
        canal["contacto"] = {"issues": True, "enlaces": [{"tipo": "discord", "url": "https://discord.gg/x"}]}
    main[f"canales/{OTRO}/canal.json"] = particion.texto_json(canal)
    filas = [miembro()] + [miembro(OTRA + i, f"m{i}", "editor") for i in range(miembros - 1)]
    main[f"canales/{OTRO}/miembros.json"] = particion.texto_json({"esquema": 1, "miembros": filas})
    parche = json.loads(main[PARCHE_ES])
    v = parche["ediciones"][0]["versiones"][0]
    v["estado"] = estado_version
    if hash_version:
        v["paquete"]["hash"] = hash_version
        v["fechaRetirada"] = retirada
    main[PARCHE_ES] = particion.texto_json(parche)
    return main


def pedir(main=None, rol=Rol.PROPIETARIO, **campos):
    p = Propuesta(main or main_para_verificar())
    p.poner(VERIFICACION_ES, verificacion(**campos))
    return juzgar(p, Permisos(Rol.NINGUNO, por_canal={OTRO: rol}, cuenta_id=YO))


class Verificacion(unittest.TestCase):
    def test_bien_pedida(self):
        self.assertEqual([], pedir())

    def test_solo_el_propietario(self):
        self.assertTrue(hay(pedir(rol=Rol.ADMINISTRADOR), "Propietario"))
        self.assertTrue(hay(pedir(rol=Rol.NINGUNO), "Propietario"))

    def test_requisitos(self):
        self.assertTrue(hay(pedir(main_para_verificar(miembros=1)), "2 miembros"))
        self.assertTrue(hay(pedir(main_para_verificar(enlace=False)), "enlace de contacto"))
        self.assertTrue(hay(pedir(main_para_verificar(estado_version="pruebas")), "versión pública"))
        self.assertEqual([], pedir(main_para_verificar(estado_version="anterior")))

    def test_retirada_por_malware_en_90_dias(self):
        main = main_para_verificar(estado_version="retirada", hash_version=HASH_MALO)
        main.update(huellas(HASH_MALO))
        self.assertTrue(hay(pedir(main), "malware"))
        main = main_para_verificar(estado_version="retirada", hash_version=HASH_MALO, retirada="2026-08-01")
        main.update(huellas(HASH_MALO))
        self.assertFalse(hay(pedir(main), "malware"))
        # Retirada por otro motivo (su hash no está en la lista negra): no cuenta.
        self.assertFalse(hay(pedir(main_para_verificar(estado_version="retirada", hash_version=HASH_MALO)), "malware"))

    def test_lo_que_pone_el_dueno_no_lo_pone_el_propietario(self):
        for campos in ({"estado": "aceptada"}, {"respuesta": "Sí"}, {"resuelta": "2026-11-24"}):
            with self.subTest(campos=campos):
                self.assertTrue(hay(pedir(**campos), "los pone el Dueño"))

    def test_campos(self):
        self.assertTrue(hay(pedir(pedidaPor=OTRA), "pedidaPor"))
        self.assertTrue(hay(pedir(canal="ornizen"), "esquema"))
        self.assertTrue(hay(pedir(motivo=""), "motivo"))
        self.assertTrue(hay(pedir(motivo="x" * 5000), "motivo"))
        self.assertTrue(hay(pedir(fecha="2020-01-01"), "fecha"))
        self.assertTrue(hay(pedir(extra=1), "solo valen"))

    def test_ya_verificado(self):
        main = main_para_verificar()
        canal = json.loads(main[f"canales/{OTRO}/canal.json"])
        canal["verificacion"] = canal_json(verificado=True)["verificacion"]
        main[f"canales/{OTRO}/canal.json"] = particion.texto_json(canal)
        self.assertTrue(hay(pedir(main), "ya está verificado"))

    def test_un_canal_que_no_existe(self):
        p = Propuesta(main_para_verificar()).poner("solicitudes/verificacion/no_existe.json",
                                                    verificacion(canal="no_existe"))
        motivos = juzgar(p, Permisos(Rol.NINGUNO, por_canal={"no_existe": Rol.PROPIETARIO}, cuenta_id=YO))
        self.assertTrue(motivos)

    def test_un_archivo_enorme(self):
        p = Propuesta(main_para_verificar()).poner(VERIFICACION_ES, b"{" + b" " * 100_000 + b"}")
        self.assertTrue(juzgar(p, Permisos(Rol.NINGUNO, por_canal={OTRO: Rol.PROPIETARIO}, cuenta_id=YO)))


class Aprobacion(unittest.TestCase):
    def evento(self, accion="labeled", etiqueta="aprobada", quien=DUENO):
        return solicitudes.aprobacion({"PR_ACCION": accion, "PR_ETIQUETA": etiqueta, "PR_ACTOR_ID": str(quien)},
                                      frozenset({DUENO}))

    def test_solo_el_dueno_y_en_su_evento(self):
        self.assertEqual("aprobada", self.evento())
        self.assertEqual("ajena", self.evento(quien=YO))       # quien la pide no se aprueba a sí mismo
        self.assertEqual("ajena", self.evento(quien=""))
        self.assertEqual("nada", self.evento(accion="synchronize"))  # una subida después no queda aprobada
        self.assertEqual("nada", self.evento(etiqueta="solicitud:canal"))
        self.assertEqual("nada", self.evento(etiqueta="Aprobada"))
        self.assertEqual("nada", solicitudes.aprobacion({}, frozenset({DUENO})))

    def test_el_flujo_de_trabajo_avisa_de_las_etiquetas(self):
        flujo = (pathlib.Path(__file__).resolve().parents[2] / ".github/workflows/permisos.yml").read_text("utf-8")
        self.assertIn("edited, labeled]", flujo)
        self.assertEqual(2, flujo.count("PR_ETIQUETA: ${{ github.event.label.name }}"))


if __name__ == "__main__":
    unittest.main()
