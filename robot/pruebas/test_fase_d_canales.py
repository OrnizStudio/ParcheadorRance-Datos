"""Fase D, entrega 1: cualquier canal publica parches, juzgado con el rol del autor en ese canal (docs/canales.md
§4.2 y §4.3).

Cada caso es una propuesta entera sobre el `main` migrado de `test_sueltos`, con un segundo canal, @rance_es, que
tiene su propio parche de «rance» y su propio repositorio de paquetes.
"""

import json
import pathlib
import sys
import time
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import particion  # noqa: E402
from permisos import Permisos, Rol, comprobar  # noqa: E402
from test_sueltos import CATALOGO, HASH, HOY, PARCHE, URL, YO, Propuesta, main_migrado  # noqa: E402

OTRO = "rance_es"
REPO_ES = "rance-es/canal-parches"
URL_ES = f"https://github.com/{REPO_ES}/releases/download/v1/rance-es.zip"
PARCHE_ES = f"canales/{OTRO}/parches/rance.json"
LISTA_ES = f"canales/{OTRO}/lista-negra.json"
HASH_MALO = "blake3:" + "c" * 64


def main_con_dos_canales():
    archivos = main_migrado()
    archivos[f"canales/{OTRO}/canal.json"] = particion.texto_json(
        {"esquema": 1, "id": OTRO, "nombre": "Rance en Español", "paquetes": [REPO_ES]})
    archivos[PARCHE_ES] = archivos[PARCHE].replace(URL.encode(), URL_ES.encode())
    return archivos


def de(canal_roles: dict, cuenta_id=YO, oficial=Rol.NINGUNO):
    return Permisos(oficial, por_canal=dict(canal_roles), cuenta_id=cuenta_id)


def juzgar(p: Propuesta, permisos: Permisos):
    texto_main = particion.texto_json(CATALOGO).decode("utf-8")
    lados = {"antes": p.antes, "despues": p.despues}
    return comprobar(p.cambios(), texto_main, texto_main.encode(), permisos,
                     leer_archivo=lambda ruta, lado: lados[lado].get(ruta),
                     leer_sueltos=lambda lado: lados[lado], hoy=HOY)


def version_nueva(url=URL_ES, huella=HASH):
    def cambio(parche):
        edicion = parche["ediciones"][0]
        edicion["versiones"].append({"version": "1.1.0", "estado": "publica", "fecha": "2026-11-24", "autor": "eva",
                                     "notas": "segunda", "paquete": {"url": url, "tamano": 6, "hash": huella}})
    return cambio


class OtroCanalPublica(unittest.TestCase):
    def test_un_editor_del_canal_publica_en_su_repositorio(self):
        p = Propuesta(main_con_dos_canales()).cambiar(PARCHE_ES, version_nueva())
        self.assertEqual([], juzgar(p, de({OTRO: Rol.EDITOR})))

    def test_el_paquete_tiene_que_estar_en_su_repositorio(self):
        # El repositorio del canal oficial no vale para @rance_es, ni uno cualquiera.
        for url in (URL.replace("rance-1.0.0", "v9"), "https://github.com/malo/repo/releases/download/v1/x.zip"):
            p = Propuesta(main_con_dos_canales()).cambiar(PARCHE_ES, version_nueva(url))
            motivos = juzgar(p, de({OTRO: Rol.EDITOR}))
            self.assertTrue(any("Releases de los repositorios de @rance_es" in m for m in motivos), motivos)

    def test_un_colaborador_del_canal_cambia_notas_pero_no_publica(self):
        notas = Propuesta(main_con_dos_canales()).cambiar(
            PARCHE_ES, lambda q: q["ediciones"][0].update(notaEdicion="Nota nueva"))
        self.assertEqual([], juzgar(notas, de({OTRO: Rol.COLABORADOR})))
        publica = Propuesta(main_con_dos_canales()).cambiar(PARCHE_ES, version_nueva())
        self.assertTrue(juzgar(publica, de({OTRO: Rol.COLABORADOR})))

    def test_el_rol_en_el_oficial_no_vale_en_otro_canal(self):
        # Administrador de @ornizen y nada en @rance_es: no toca el parche de @rance_es.
        p = Propuesta(main_con_dos_canales()).cambiar(PARCHE_ES, version_nueva())
        motivos = juzgar(p, de({"ornizen": Rol.ADMINISTRADOR}, oficial=Rol.ADMINISTRADOR))
        self.assertTrue(any("No eres miembro de @rance_es" in m for m in motivos), motivos)

    def test_el_rol_en_otro_canal_no_vale_en_el_oficial(self):
        p = Propuesta(main_con_dos_canales()).cambiar(PARCHE, lambda q: q["ediciones"][0].update(notaEdicion="x"))
        motivos = juzgar(p, de({OTRO: Rol.PROPIETARIO}))
        self.assertTrue(any("No eres miembro de @ornizen" in m for m in motivos), motivos)

    def test_una_propuesta_un_canal(self):
        p = (Propuesta(main_con_dos_canales())
             .cambiar(PARCHE_ES, lambda q: q["ediciones"][0].update(notaEdicion="a"))
             .cambiar(PARCHE, lambda q: q["ediciones"][0].update(notaEdicion="b")))
        motivos = juzgar(p, de({OTRO: Rol.PROPIETARIO, "ornizen": Rol.PROPIETARIO}, oficial=Rol.PROPIETARIO))
        self.assertTrue(any("varios canales" in m for m in motivos), motivos)

    def test_un_canal_no_toca_lo_central_en_la_misma_propuesta(self):
        p = (Propuesta(main_con_dos_canales())
             .cambiar(PARCHE_ES, lambda q: q["ediciones"][0].update(notaEdicion="a"))
             .cambiar("juegos/rance/juego.json", lambda j: j.update(sinopsis="Otra")))
        motivos = juzgar(p, de({OTRO: Rol.PROPIETARIO}))
        self.assertTrue(any("solo cambia `canales/rance_es/`" in m for m in motivos), motivos)

    def test_anadir_un_juego_al_canal_es_de_administrador(self):
        def con_juego(archivos):
            archivos = dict(archivos)
            del archivos[PARCHE_ES]
            return archivos
        p = Propuesta(con_juego(main_con_dos_canales()))
        p.poner(PARCHE_ES, main_con_dos_canales()[PARCHE_ES])
        self.assertEqual([], juzgar(p, de({OTRO: Rol.ADMINISTRADOR})))
        self.assertTrue(juzgar(p, de({OTRO: Rol.EDITOR})))

    def test_un_juego_que_no_existe_no_se_publica(self):
        parche = json.loads(main_con_dos_canales()[PARCHE_ES])
        parche["juego"] = "inventado"
        p = Propuesta(main_con_dos_canales()).poner(f"canales/{OTRO}/parches/inventado.json", parche)
        self.assertTrue(juzgar(p, de({OTRO: Rol.PROPIETARIO})))

    def test_añadirse_uno_mismo_en_la_propuesta_no_da_permiso(self):
        miembros = {"esquema": 1, "miembros": [
            {"id": YO, "cuenta": "yo", "rol": "propietario", "desde": "2026-11-24", "estado": "activo"}]}
        p = (Propuesta(main_con_dos_canales())
             .poner(f"canales/{OTRO}/miembros.json", miembros)
             .cambiar(PARCHE_ES, version_nueva()))
        motivos = juzgar(p, de({}))
        self.assertTrue(any("No eres miembro de @rance_es" in m for m in motivos), motivos)


class ListaNegraDelCanal(unittest.TestCase):
    def lista(self, huella=HASH_MALO):
        return {"esquema": 1, "archivos": [], "usuarios": [],
                "huellas": [{"hash": huella, "motivo": "Minero en un .dll", "fecha": "2026-11-20"}]}

    def test_un_paquete_con_huella_vetada_por_su_canal_no_entra(self):
        main = main_con_dos_canales()
        main[LISTA_ES] = particion.texto_json(self.lista())
        p = Propuesta(main).cambiar(PARCHE_ES, version_nueva(huella=HASH_MALO.upper().replace("BLAKE3", "blake3")))
        motivos = juzgar(p, de({OTRO: Rol.EDITOR}))
        self.assertTrue(any("lista negra de @rance_es" in m and "Minero" in m for m in motivos), motivos)

    def test_la_huella_vetada_en_la_misma_propuesta_tambien_cuenta(self):
        p = (Propuesta(main_con_dos_canales())
             .cambiar(PARCHE_ES, version_nueva(huella=HASH_MALO)))
        p.poner(LISTA_ES, self.lista())
        motivos = juzgar(p, de({OTRO: Rol.ADMINISTRADOR}))
        self.assertTrue(any("lista negra de @rance_es" in m for m in motivos), motivos)

    def test_la_lista_de_otro_canal_no_afecta(self):
        main = main_con_dos_canales()
        main["canales/ornizen/lista-negra.json"] = particion.texto_json(self.lista())
        p = Propuesta(main).cambiar(PARCHE_ES, version_nueva(huella=HASH_MALO))
        self.assertEqual([], juzgar(p, de({OTRO: Rol.EDITOR})))


class Extremos(unittest.TestCase):
    def test_cinco_mil_canales(self):
        main = main_con_dos_canales()
        for i in range(5000):
            main[f"canales/c{i:04d}/canal.json"] = particion.texto_json(
                {"esquema": 1, "id": f"c{i:04d}", "nombre": f"Canal {i}", "paquetes": [f"c{i}/canal-parches"]})
        p = Propuesta(main).cambiar(PARCHE_ES, version_nueva())
        inicio = time.monotonic()
        self.assertEqual([], juzgar(p, de({OTRO: Rol.EDITOR})))
        self.assertLess(time.monotonic() - inicio, 20)

    def test_varias_cuentas_no_publican_en_otro_canal(self):
        # Quien abrió la propuesta y quien subió el último cambio no son la misma cuenta: sin cuenta, no.
        p = Propuesta(main_con_dos_canales()).cambiar(PARCHE_ES, version_nueva())
        motivos = juzgar(p, de({OTRO: Rol.PROPIETARIO}, cuenta_id=None))
        self.assertTrue(any("varias cuentas" in m for m in motivos), motivos)


class RevisionD1(unittest.TestCase):
    """Revisión de seguridad de la entrega 1: un caso por fallo."""

    def con_paquetes(self, p, permisos, leer_paquete):
        texto_main = particion.texto_json(CATALOGO).decode("utf-8")
        lados = {"antes": p.antes, "despues": p.despues}
        return comprobar(p.cambios(), texto_main, texto_main.encode(), permisos, leer_paquete=leer_paquete,
                         leer_archivo=lambda ruta, lado: lados[lado].get(ruta),
                         leer_sueltos=lambda lado: lados[lado], hoy=HOY)

    # 1. Los paquetes de las versiones nuevas se bajan y se revisan, con tope.
    def test_el_paquete_de_una_version_nueva_se_revisa(self):
        vistos = []

        def leer_paquete(paquete):
            vistos.append(paquete["url"])
            return ["Rance.exe"]
        url = URL_ES.replace("rance-es.zip", "v2.zip")
        p = Propuesta(main_con_dos_canales()).cambiar(PARCHE_ES, version_nueva(url, "blake3:" + "a" * 64))
        self.assertEqual([], self.con_paquetes(p, de({OTRO: Rol.EDITOR}), leer_paquete))
        self.assertEqual([url], vistos)

    def test_el_paquete_de_una_version_nueva_que_no_se_puede_revisar(self):
        from permisos import PaqueteIlegible

        def leer_paquete(paquete):
            raise PaqueteIlegible("no coincide el hash.")
        url = URL_ES.replace("rance-es.zip", "v2.zip")
        p = Propuesta(main_con_dos_canales()).cambiar(PARCHE_ES, version_nueva(url, "blake3:" + "a" * 64))
        motivos = self.con_paquetes(p, de({OTRO: Rol.EDITOR}), leer_paquete)
        self.assertTrue(any("no se ha podido revisar" in m for m in motivos), motivos)

    def test_mil_quinientas_versiones_nuevas_no_se_bajan_todas(self):
        llamadas = []

        def muchas(parche):
            for i in range(1500):
                parche["ediciones"][0]["versiones"].append({
                    "version": f"2.{i}.0", "estado": "pruebas", "fecha": "2026-11-24", "autor": "eva", "notas": "x",
                    "paquete": {"url": URL_ES.replace("rance-es.zip", f"v{i}.zip"), "tamano": 6,
                                "hash": f"blake3:{i:064x}"}})
        p = Propuesta(main_con_dos_canales()).cambiar(PARCHE_ES, muchas)
        motivos = self.con_paquetes(p, de({OTRO: Rol.EDITOR}), lambda q: llamadas.append(q) or [])
        self.assertTrue(any("más de 20 paquetes nuevos" in m for m in motivos), motivos)
        self.assertLessEqual(len(llamadas), 20)

    # 2. Un canal retirado o bloqueado no publica.
    def con_estado(self, estado):
        main = main_con_dos_canales()
        canal = json.loads(main_con_dos_canales()[f"canales/{OTRO}/canal.json"])
        canal["estado"] = estado
        main[f"canales/{OTRO}/canal.json"] = particion.texto_json(canal)
        return main

    def test_un_canal_retirado_no_publica_versiones(self):
        p = Propuesta(self.con_estado("retirado")).cambiar(PARCHE_ES, version_nueva())
        motivos = juzgar(p, de({OTRO: Rol.PROPIETARIO}))
        self.assertTrue(any("está retirado" in m for m in motivos), motivos)
        p = Propuesta(self.con_estado("retirado")).cambiar(PARCHE_ES, lambda q: q.update(orden=5))
        self.assertTrue(any("está retirado" in m for m in juzgar(p, de({OTRO: Rol.PROPIETARIO}))))

    def test_un_canal_retirado_retira_versiones_y_oculta(self):
        def retirar(parche):
            parche["ediciones"][0]["versiones"][0].update(estado="retirada", motivo="cerrado", motivoPublico=True,
                                                          fechaRetirada="2026-11-24")
        p = Propuesta(self.con_estado("retirado")).cambiar(PARCHE_ES, retirar)
        self.assertFalse(any("está retirado" in m for m in juzgar(p, de({OTRO: Rol.PROPIETARIO}))))
        p = Propuesta(self.con_estado("retirado")).cambiar(PARCHE_ES, lambda q: q.update(habilitado=False))
        self.assertFalse(any("está retirado" in m for m in juzgar(p, de({OTRO: Rol.PROPIETARIO}))))

    def test_un_canal_bloqueado_no_cambia_nada(self):
        for cambio in (version_nueva(), lambda q: q.update(habilitado=False)):
            p = Propuesta(self.con_estado("bloqueado")).cambiar(PARCHE_ES, cambio)
            self.assertTrue(any("bloqueado" in m for m in juzgar(p, de({OTRO: Rol.PROPIETARIO}))))

    def test_cerrar_el_canal_y_publicar_a_la_vez(self):
        p = Propuesta(main_con_dos_canales()).cambiar(PARCHE_ES, version_nueva())
        canal = json.loads(main_con_dos_canales()[f"canales/{OTRO}/canal.json"])
        canal["estado"] = "retirado"
        p.poner(f"canales/{OTRO}/canal.json", canal)
        self.assertTrue(any("está retirado" in m for m in juzgar(p, de({OTRO: Rol.PROPIETARIO}))))

    # 3. Una huella vetada no vuelve por otra versión ni des-retirando una.
    def con_retirada_mala(self):
        main = main_con_dos_canales()
        main[LISTA_ES] = particion.texto_json(ListaNegraDelCanal().lista())
        parche = json.loads(main[PARCHE_ES])
        parche["ediciones"][0]["versiones"].append({
            "version": "0.9.0", "estado": "retirada", "fecha": "2026-10-01", "autor": "ana", "notas": "mala",
            "motivo": "minero", "fechaRetirada": "2026-10-02",
            "paquete": {"url": URL_ES.replace("rance-es.zip", "malo.zip"), "tamano": 7, "hash": HASH_MALO}})
        main[PARCHE_ES] = particion.texto_json(parche)
        return main

    def test_des_retirar_una_version_vetada(self):
        def des_retirar(parche):
            v = parche["ediciones"][0]["versiones"][1]
            v["estado"] = "pruebas"
            for k in ("motivo", "fechaRetirada"):
                v.pop(k)
        p = Propuesta(self.con_retirada_mala()).cambiar(PARCHE_ES, des_retirar)
        motivos = juzgar(p, de({OTRO: Rol.EDITOR}))
        self.assertTrue(any("lista negra de @rance_es" in m for m in motivos), motivos)

    def test_la_huella_vetada_en_otra_version(self):
        p = Propuesta(self.con_retirada_mala()).cambiar(
            PARCHE_ES, version_nueva(URL_ES.replace("rance-es.zip", "malo.zip"), HASH_MALO))
        motivos = juzgar(p, de({OTRO: Rol.EDITOR}))
        self.assertTrue(any("lista negra de @rance_es" in m for m in motivos), motivos)

    def test_la_retirada_mala_no_estorba_lo_demas(self):
        p = Propuesta(self.con_retirada_mala()).cambiar(PARCHE_ES, lambda q: q.update(sinopsis="otra"))
        self.assertFalse(any("lista negra" in m for m in juzgar(p, de({OTRO: Rol.EDITOR}))))

    # 4. `habilitado`, `orden` y etiquetas son de Administrador o más (§4.2).
    def test_orden_y_etiquetas_de_administrador(self):
        for cambio in (lambda q: q.update(orden=7), lambda q: q.update(etiquetas=[]),
                       lambda q: q.update(habilitado=False)):
            for rol in (Rol.EDITOR, Rol.COLABORADOR):
                with self.subTest(rol=rol):
                    p = Propuesta(main_con_dos_canales()).cambiar(PARCHE_ES, cambio)
                    self.assertTrue(juzgar(p, de({OTRO: rol})), rol)
            p = Propuesta(main_con_dos_canales()).cambiar(PARCHE_ES, cambio)
            self.assertEqual([], juzgar(p, de({OTRO: Rol.ADMINISTRADOR})))


if __name__ == "__main__":
    unittest.main()
