# Arquitectura cognitiva v2 — guía práctica

Esta versión convierte parte de la arquitectura conceptual en un programa
verificable. Conserva el historial y los documentos anteriores. JEV continúa en
su instalación canónica; este paquete se conecta a ella y no la reemplaza.

## Uso sin modelos

```powershell
python -m pip install -e .
python -m cognitive_architecture run examples/offline-task.json
python -m cognitive_architecture graph examples/knowledge-graph.json
python -m unittest discover -s tests -v
```

El ejemplo cuenta texto español correctamente en Unicode y UTF-8. Una segunda
ejecución reutiliza el resultado validado. No requiere claves ni servicios.

## Uso con modelos

Copia examples/config.example.json a .cognition/config.json y sustituye los IDs
por modelos disponibles en tu cuenta. El primero realiza el trabajo inicial;
los siguientes solo intervienen cuando falla una comprobación de aceptación.
Codex CLI debe estar instalado y autenticado. No existe fallback automático a
una API de pago.

Para conectar JEV utiliza examples/config.jev.example.json. La lista connector
contiene el Python de JEV y los argumentos -m jev_orchestrator.connection.
El campo cwd apunta a su carpeta. No copies claves: el conector mantiene su
propia gestión de credenciales. Con collaboration=auto, JEV decide el modo;
los otros modos se solicitan explícitamente y no consultan al router.

## Qué demuestra una ejecución

accepted significa que la salida final cumple exactamente los checks declarados.
Una búsqueda de palabras demuestra formato, no veracidad científica. Las pruebas
del proyecto verifican el comportamiento del programa, no una mejora general de
inteligencia o un ahorro universal de tokens.

El límite de llamadas se aplica a cada invocación de router o trabajador, incluso
si falla. Tiempo y tokens se comprueban entre llamadas; una llamada en curso puede
sobrepasarlos y entonces el resultado no se acepta como dentro del presupuesto.
Si el proveedor no informa consumo, se conserva como desconocido.

Los checkpoints permiten inspeccionar estado y repetir una tarea; no reanudan
automáticamente un panel interrumpido. Los dos modos de panel usan dos opiniones
independientes y una síntesis revisora. Solo se valida la síntesis entregada.

## HUEVOS como ejemplo

El grafo de ejemplo organiza objetivo, evidencia, restricciones y aceptación para
las pruebas de cáscara/relleno. El panel propone un plan experimental. No contiene
resultados medidos ni promete una mejora de velocidad.
