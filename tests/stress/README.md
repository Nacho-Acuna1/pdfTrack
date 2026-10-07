# Pruebas de carga

Los dos scripts usan los cuatro archivos de `pdfs/` y escriben sus resultados en
`results/`.

```bash
./tests/stress/run_k6.sh
./tests/stress/run_vegeta.sh
```

Para cambiar el destino sin editar los scripts:

```bash
BASE_URL=http://localhost:8000 ./tests/stress/run_k6.sh
BASE_URL=http://localhost:8000 ./tests/stress/run_vegeta.sh
```
