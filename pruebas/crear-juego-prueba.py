#!/usr/bin/env python3
"""Crea el «Juego de prueba»: dos carpetas inventadas (original y traducida) para probar el parcheador.

No contiene nada de ningún juego real: todo el contenido se genera aquí. Siempre sale idéntico, así que
la huella del catálogo y el paquete del parche se pueden volver a crear en cualquier equipo.

Uso:  python pruebas/crear-juego-prueba.py <carpeta de salida>
Deja  <salida>/original  y  <salida>/traducida.
"""
import hashlib
import pathlib
import sys


def relleno(semilla: str, tamano: int) -> bytes:
    """Bytes que parecen datos binarios, siempre los mismos para la misma semilla."""
    trozos, i = [], 0
    while sum(map(len, trozos)) < tamano:
        trozos.append(hashlib.sha256(f"{semilla}:{i}".encode()).digest())
        i += 1
    return b"".join(trozos)[:tamano]


def lineas(idioma: str) -> bytes:
    frases = {
        "ja": ["テスト用の文章です。", "これは本物のゲームではありません。", "パッチの確認用。"],
        "es": ["Texto de prueba.", "Esto no es un juego de verdad.", "Sirve para comprobar el parche."],
    }[idioma]
    return "\n".join(f"{n:04d} {frases[n % 3]}" for n in range(400)).encode("utf-8")


def escribir(raiz: pathlib.Path, ruta: str, datos: bytes) -> None:
    destino = raiz / ruta
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(datos)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    salida = pathlib.Path(sys.argv[1])
    original, traducida = salida / "original", salida / "traducida"

    ejecutable = b"Este archivo no es un programa: solo sirve para que el parcheador reconozca la carpeta.\n"
    graficos = relleno("graficos", 300_000)
    cabecera, cola = relleno("cabecera", 150_000), relleno("cola", 150_000)

    # Original: lo que tendría el usuario recién instalado.
    escribir(original, "JuegoDePrueba.exe", ejecutable)
    escribir(original, "Datos/textos.dat", cabecera + lineas("ja") + cola)
    escribir(original, "Datos/graficos.dat", graficos)
    escribir(original, "LEEME.txt", "Juego de prueba del Parcheador Rance. No es un juego real.\n".encode())

    # Traducida: cambia el texto (diff), deja igual lo demás y añade una «fuente» (archivo nuevo).
    escribir(traducida, "JuegoDePrueba.exe", ejecutable)
    escribir(traducida, "Datos/textos.dat", cabecera + lineas("es") + cola)
    escribir(traducida, "Datos/graficos.dat", graficos)
    escribir(traducida, "LEEME.txt", "Juego de prueba del Parcheador Rance. No es un juego real.\n".encode())
    escribir(traducida, "Fuentes/fuente-de-prueba.ttf", relleno("fuente", 20_000))

    print(f"Hecho: {original} y {traducida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
