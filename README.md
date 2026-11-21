# ParcheadorRance-Datos

Los datos públicos del **Parcheador Central Rance**: el programa que instala las traducciones al español
de los juegos de Rance. El programa no trae nada escrito dentro: todo lo que enseña (juegos, versiones,
textos, imágenes) sale de aquí.

Aquí **no hay nada de los juegos originales**. Los parches solo contienen las diferencias entre el juego
original y el traducido, y el catálogo solo tiene nombres de archivo, tamaños y «hashes» (una especie de
huella dactilar de cada archivo, con la que no se puede reconstruir el juego).

## Qué hay en este repositorio

| Sitio | Qué es |
|---|---|
| [`catalogo/catalogo.json`](catalogo/catalogo.json) | **El catálogo**: la lista de juegos, ediciones, versiones de parche, textos y etiquetas. Es lo que el parcheador descarga al abrirse. |
| `catalogo/juegos/<juego>/` | Las imágenes de cada juego (icono, banner, fondo, logo, portada). El catálogo las nombra con rutas relativas a `catalogo/`. |
| [Releases](../../releases) | Los **paquetes de parche** (`<juego>-<edición>-<versión>.zip`) y, más adelante, las versiones del propio parcheador. |
| [`robot/`](robot/) y [`.github/workflows/`](.github/workflows/) | El **robot de permisos**: revisa cada cambio propuesto y lo publica solo si quien lo hace tiene permiso. Solo lo cambia el Propietario. |
| [`normas/`](normas/) | Las normas generales, que solo cambia el Propietario: los archivos que **ningún parche puede tocar** (protección anticopia y cracks) y la cuenta del Propietario. |
| [`pruebas/`](pruebas/) | El «Juego de prueba»: un juego inventado para probar el parcheador de principio a fin. |

## La dirección del catálogo

El parcheador descarga siempre esta dirección:

```
https://raw.githubusercontent.com/OrnizStudio/ParcheadorRance-Datos/main/catalogo/catalogo.json
```

Es la dirección «raw» del archivo en la rama `main`. Se eligió en lugar de GitHub Pages porque:

- **No hay paso intermedio que pueda fallar**: lo que hay en `main` es lo que se sirve. Con Pages, cada
  cambio pasa antes por una publicación que tarda y a veces falla, y el catálogo se quedaría viejo sin avisar.
- **Tarda unos 5 minutos** en verse un cambio (GitHub guarda una copia ese tiempo); Pages, unos 10.
- Pages queda libre para el panel web del equipo.

Esa dirección está escrita dentro del parcheador, así que **no se puede renombrar** el repositorio, la
rama `main`, la carpeta `catalogo/` ni el archivo sin sacar antes una versión nueva del parcheador.

## Cómo se publica un cambio

1. Se cambia `catalogo/catalogo.json` (y las imágenes, si toca).
2. **Se sube `versionCatalogo` en 1.** El parcheador solo usa un catálogo si su número es mayor que el que
   ya tiene; si no sube, nadie se entera del cambio.
3. Los Administradores pueden subirlo directamente a `main`. Los Editores y Colaboradores lo mandan como
   propuesta (pull request) y el robot la revisa y la publica sola.

Para publicar un parche nuevo:

1. Crear el paquete con `parcheador-publicador paquete …` (da el `.zip` y el texto para el catálogo).
2. Subir el `.zip` a una Release con la etiqueta `<juego>-<versión>` (por ejemplo `prueba-0.1.0`). Una
   Release por versión del parche; dentro va un `.zip` por edición.
3. Pegar en el catálogo el `paquete` (con la dirección del `.zip` en la Release, `tamano` y `hash`) y las
   huellas, y subir `versionCatalogo`.

Un `.zip` ya publicado **no se sustituye nunca**: el catálogo guarda su tamaño y su hash, y el parcheador
rechaza un archivo que no coincida. Si hay que corregir algo, se publica una versión nueva.

## Roles y robot de permisos

| Rol | Equipo de GitHub | Nivel en este repositorio | Qué puede cambiar |
|---|---|---|---|
| Propietario | `administradores` (y *owner* de la organización) | Admin | Todo, también las normas generales (`normas/`), el robot (`robot/`), la configuración de GitHub (`.github/`) y las **etiquetas del catálogo** (crearlas, editarlas y borrarlas: son globales). |
| Administrador | `administradores` | Admin | Todo menos `normas/`, `robot/` y `.github/`, y menos crear, editar o borrar etiquetas del catálogo (poner y quitar en un juego las que ya existen, sí). |
| Editor | `editores` | Escritura (*write*) | El contenido de los juegos **que ya existen**: ediciones, versiones (crearlas, publicarlas, retirarlas), textos, imágenes, etiquetas puestas, créditos. No puede dar de alta, quitar, publicar ni ocultar un juego entero, ni tocar el parcheador (`launcher`), el grupo, las etiquetas del catálogo o cualquier archivo fuera de `catalogo/`. |
| Colaborador | `colaboradores` | Clasificación (*triage*) | Solo, en juegos y versiones que ya existen: **textos y notas** (`sinopsis`, `notaEdicion`, `parche.notas`), **etiquetas** (poner y quitar las que existen) y **estado de la traducción** (`estado`, `progreso`, `contenido`). |

Cómo funciona:

- La rama `main` está protegida: nadie que no sea Administrador puede escribir en ella directamente. Los
  cambios llegan como propuesta y la comprobación **`permisos`** es obligatoria.
- El robot ([`robot/permisos.py`](robot/permisos.py)) mira qué archivos y qué campos del catálogo cambia la
  propuesta, y el rol de quien la hace. Si todo está permitido, **la publica sola en menos de un minuto**.
  Si no, deja un comentario en la propuesta explicando, en lenguaje claro, qué no puede aceptar y por qué.
- A todos, también a los Administradores que usen propuestas, les comprueba que el catálogo se pueda leer,
  que `versionCatalogo` suba, que las etiquetas usadas existan y que los paquetes lleven dirección `https`,
  tamaño y hash.
- Un borrador (*draft*) se comprueba pero no se publica hasta marcarlo como listo.
- Los Colaboradores no pueden crear ramas aquí: proponen desde una copia propia del repositorio (*fork*).
  Los Editores sí pueden crear ramas (necesitan escritura para subir paquetes a las Releases).
- Cuenta el rol más bajo entre quien abrió la propuesta y quien subió el último cambio.
- `normas/`, `robot/` y `.github/` **solo los cambia el Propietario**, ni siquiera los Administradores: son
  las normas generales y lo que las hace cumplir. Si un Administrador pudiera cambiar el robot o sus flujos
  de trabajo, podría quitar cualquier regla. Quién es el Propietario lo dice
  [`normas/propietario.json`](normas/propietario.json) (ver «Archivos prohibidos»).

### Archivos prohibidos (protección anticopia)

Esta herramienta es para traducciones de juegos que la gente ya tiene, **no para distribuir cracks**. Por
eso ningún parche puede modificar ni añadir archivos de protección anticopia (DRM), las bibliotecas de las
tiendas que comprueban que el juego es tuyo (Steam, GOG Galaxy, Epic, Ubisoft Connect) ni los archivos
típicos de los cracks y emuladores de Steam.

Hay **dos listas** y cuentan las dos a la vez:

| Lista | Dónde está | Para qué parches | Quién la cambia |
|---|---|---|---|
| **General** | [`normas/archivos-prohibidos.json`](normas/archivos-prohibidos.json) | Todos. | Solo el **Propietario**. El robot la lee siempre de `main`. |
| **Del grupo** | `grupo.archivosProhibidos` en el catálogo (la ficha del grupo) | Los de este catálogo, que son los del grupo. | Quien puede cambiar la ficha del grupo: Administradores y Propietario. |

- Las dos tienen el mismo formato: una lista de `{ "patron": "…", "motivo": "…" }`. Por ejemplo:
  ```json
  "grupo": { "nombre": "Ornizen", "archivosProhibidos": [ { "patron": "*.sig", "motivo": "Firma de los datos del juego." } ] }
  ```
- La del grupo **solo añade**. No hay forma de escribir una excepción, así que nunca quita ni se salta nada
  de la general. Si un grupo quita una entrada suya, el cambio vale a partir de la propuesta siguiente:
  en la misma propuesta todavía cuenta la lista que había en `main`.
- El aviso dice de qué lista viene el bloqueo: «general» o «del grupo X». Si un archivo está en las
  dos, dice «general».
- El Propietario es el *owner* de la organización. El robot no puede distinguirlo de un Administrador (los
  dos tienen nivel *admin*), así que su cuenta está escrita en [`normas/propietario.json`](normas/propietario.json).
  Todo lo que hay en `normas/` lo cambia solo el Propietario, también ese archivo. Si cambia la cuenta del
  Propietario, hay que cambiarla allí.
- Más adelante, con los canales comunitarios, cada canal tendrá su lista propia con la misma regla: solo
  añadir.
- Cómo se escriben los patrones (sin distinguir mayúsculas; `*` vale por cualquier cosa):
  - `steam_api64.dll` o `uplay_r1_loader*.dll`: el **nombre del archivo**, en cualquier carpeta del juego;
  - `steam_settings/` (con barra al final): **cualquier archivo dentro de una carpeta** con ese nombre;
  - `bin/*.sig` (con una barra en medio): la **ruta entera** desde la carpeta del juego.
- **No hay excepciones por rol**: la regla vale también para Administradores y Propietario. Si el robot
  la aplica, la propuesta no se publica. El mensaje es: «Este parche toca un archivo protegido (X). Los
  parches no pueden modificar archivos de protección anticopia.»
- Qué mira el robot:
  1. las rutas de `huellasParcheadas` del catálogo (lo que dice cada versión que deja en el juego);
  2. **cada paquete nuevo** que aparece en el catálogo (en `parche.paquetes` o en el historial de
     versiones): lo descarga, comprueba que su tamaño y su hash BLAKE3 son los del catálogo (los mismos que
     exige el parcheador antes de instalarlo) y lee las rutas de su `manifiesto.json`, que es lo que
     escribe de verdad el parcheador. Nunca ejecuta nada del paquete. Si no puede descargarlo o no
     coincide, rechaza la propuesta: sin revisarlo no se puede saber qué toca. Por eso **el `.zip` tiene
     que estar ya subido a la Release** antes de proponer el cambio del catálogo.
  3. Los paquetes que ya estaban publicados no se vuelven a descargar.
- La huella del juego **original** (`huella` de cada edición) sí puede llevar estos archivos: describe el
  juego tal como se compra, no lo que cambia el parche.
- Para BLAKE3 el robot instala el paquete `blake3` de PyPI con la versión y el hash fijados en
  [`robot/requisitos.txt`](robot/requisitos.txt). Es lo único que instala de fuera.

Límites que conviene conocer:

- El robot sabe el rol por el **nivel de acceso** de cada cuenta en este repositorio, que es lo único que
  puede consultar sin una clave propia. Por eso cada equipo tiene un nivel distinto: no hay que cambiarlos.
- Un Editor tiene escritura, y con escritura una persona con conocimientos técnicos y mala intención
  podría saltarse la comprobación (por ejemplo, subiendo a una rama una automatización que la dé por
  buena). El robot evita errores y excesos, pero **el rol de Editor es para gente de confianza**. Todo
  queda en el historial con su autor y se puede deshacer. Un Colaborador no tiene esa posibilidad.
- Las reglas se prueban con `python -m unittest discover -s robot/pruebas`.
- La protección de `main` no se aplica a los Administradores (*enforce admins* desactivado): un
  Administrador puede subir directamente a `main` o publicar una propuesta sin esperar al robot, y así se
  saltaría también la lista de archivos prohibidos. La regla es la misma para todos; el robot solo la hace
  cumplir en las propuestas.

Preparado para más adelante (sin hacer): que cada juego tenga su líder y su equipo. Las reglas ya preguntan
el rol «en este juego»; bastará con que el robot lea los permisos de un archivo `equipo.json` (está
indicado dónde, en `leer_equipo` de `robot/permisos.py`).

### Archivos ignorados de una edición

Cada edición puede llevar `ignorar`: una lista de patrones, al estilo de un `.gitignore`, con los archivos de
la carpeta del juego que **no cuentan para reconocer la edición** (configuración, caché: lo que el juego o el
usuario cambian). No entran en la `huella` y el parcheador no los mira al detectar.

```json
{ "id": "steam", "ignorar": ["config.ini", "UserData/**"], "ignorados": { "archivos": 3, "bytes": 90 } }
```

La lista se escribe en el parcheador (Equipo → Registrar edición), que tiene la carpeta delante y enseña
cuánto deja fuera. Tiene límites, para que nadie deje la huella en «todo ignorado menos el `.exe`», y el
robot los vuelve a comprobar para cualquier rol, también Administradores y Propietario:

- **Patrones prohibidos**: los que valen para cualquier archivo (`*`, `**`, `**/*`, `*.*`, `*/*`), los vacíos,
  los que salen de la carpeta (`..`, rutas absolutas) y los de ejecutables (`.exe`, `.dll`).
- Como mucho **50 patrones** de 200 caracteres.
- **Nunca pueden ignorar un archivo que el parche modifica**: ni los de `huellasParcheadas` ni, en un paquete
  nuevo, los de su manifiesto.
- Lo ignorado **no puede seguir en la `huella`**.
- En la huella tiene que quedar **al menos el 80 % del tamaño y el 70 % de los archivos**. Como el robot no
  ve la carpeta del juego, lo comprueba con `ignorados` (cuántos archivos y bytes deja fuera la lista), que
  escribe el parcheador. Sin `ignorados` la lista no se acepta.

Lo que el robot no puede comprobar y sí hace el parcheador, con la carpeta delante: que un patrón solo no pase
del 10 % del tamaño ni del 20 % de los archivos, y que no se ignoren los 10 archivos más grandes.

## Contenido de pruebas

Los juegos, ediciones y versiones marcados con `"pruebas": true` **no los ve el público**: el parcheador
los quita al cargar el catálogo. Solo los ve el equipo. Mientras el parcheador no tenga inicio de sesión,
el equipo lo abre con el argumento `--equipo`:

```
ParcheadorCentralRance.exe --equipo
```

Ojo: `pruebas` solo **oculta**, no protege. Este repositorio es público y cualquiera puede leer el catálogo
y descargar los paquetes de las Releases. No pongas en pruebas nada que no pueda verse.

### El «Juego de prueba»

Es un juego inventado (id `prueba`) para comprobar el parcheador de verdad sin tocar ningún juego real.
Para usarlo:

1. Descarga `juego-de-prueba-original.zip` de la Release [`prueba-0.1.0`](../../releases/tag/prueba-0.1.0)
   y descomprímelo donde quieras.
2. Abre el parcheador con `--equipo`, entra en «Juego de prueba» y añade esa carpeta.
3. Instala el parche, comprueba que `Datos/textos.dat` pasa a estar en español y que aparece
   `Fuentes/fuente-de-prueba.ttf`, y quítalo para ver que todo vuelve a como estaba.

«Jugar» no funciona con él: `JuegoDePrueba.exe` es un archivo de texto, no un programa.

Las carpetas se generan con [`pruebas/crear-juego-prueba.py`](pruebas/crear-juego-prueba.py) y salen
siempre idénticas, así que el paquete se puede volver a crear en cualquier equipo.
