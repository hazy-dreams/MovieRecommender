# Private VPS Preview

This is an operator runbook for a private, manually visitable preview of the
current Django app. It uses the bounded SQLite recommendation path already in
the repo and intentionally avoids public DNS, TLS, production deployment, and
new serving architecture.

## Build Preview Artifacts

Use existing reduced artifacts when they are already available:

```bash
python recommender.py movies_10.csv "Inception" \
  --store movies_10.sqlite \
  --candidate-limit 500
```

If real IMDb TSVs or reduced artifacts are unavailable, build the tiny offline
fixture instead. These generated files are under ignored paths and must not be
committed:

```bash
make setup
mkdir -p data/preview
make imdb-bootstrap ARGS="--sample --output-dir data/imdb-sample"
make canonical-dataset \
  IMDB_DATA_DIR=data/imdb-sample \
  DATASET_OUTPUT=data/preview/movies_preview \
  DATASET_PERCENTAGE=0 \
  DATASET_MIN_VOTES=0
python recommender.py data/preview/movies_preview.csv "Sample Movie" \
  --store data/preview/movies_preview.sqlite \
  --candidate-limit 250
```

## Start The Private Preview

SSH tunnel mode keeps Django bound to loopback on the VPS:

```bash
RECOMMENDER_DATASET_PATH=data/preview/movies_preview.csv \
RECOMMENDER_STORE_PATH=data/preview/movies_preview.sqlite \
RECOMMENDER_CANDIDATE_LIMIT=250 \
make run-web WEB_BIND=127.0.0.1:8000
```

From your workstation, open a tunnel to the VPS:

```bash
ssh -N -L 8000:127.0.0.1:8000 <vps-ssh-host>
```

Then visit `http://127.0.0.1:8000/` locally.

Trusted private-network mode is also acceptable when the VPS firewall and
network already restrict access. Bind to the private interface and set the
expected hostnames or private IPs:

```bash
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost,<private-host-or-ip> \
RECOMMENDER_DATASET_PATH=data/preview/movies_preview.csv \
RECOMMENDER_STORE_PATH=data/preview/movies_preview.sqlite \
RECOMMENDER_CANDIDATE_LIMIT=250 \
make run-web WEB_BIND=0.0.0.0:8000
```

Visit `http://<private-host-or-ip>:8000/` from the trusted network only.

## Smoke Checks

Run the Django checks before starting the preview:

```bash
make smoke
```

After the server starts, verify the page is reachable:

```bash
curl -fsS http://127.0.0.1:8000/ >/tmp/movierec-preview-home.html
```

Use the browser for recommendation requests so Django's CSRF form flow is
exercised normally.

The development server can warn about unapplied Django admin/auth/session
migrations in a fresh checkout. The search preview path does not use those
tables. To silence the warning for a longer manual session, run:

```bash
.venv/bin/python webapp/manage.py migrate
```

## Shutdown

Stop the Django server with `Ctrl-C`. Stop the SSH tunnel with `Ctrl-C` in the
tunnel terminal. Generated preview artifacts can be removed when no longer
needed:

```bash
rm -rf data/preview data/imdb-sample
```

## Manual E2E Checklist

Record these observations in the issue or PR report after running the preview:

| Check | Action | Expected or observed result |
| --- | --- | --- |
| Homepage loads | Visit `http://127.0.0.1:8000/` through the tunnel, or the private-network URL. | Search form renders with HTTP 200. |
| Known-title recommendation | Search `Sample Movie` when using the fixture, or a known title from the real artifact. | Fixture returns `Sample Sequel`; real artifact returns recommendations from the SQLite store. |
| Missing-title error | Search a title that is not in the artifact. | Page stays usable and shows `This movie is not in the dataset.` |
| Duplicate-title behavior | If the artifact contains duplicate primary titles, search the disambiguated `Title (tconst)` value. | The app accepts the disambiguated title; sample fixture has no duplicate-title case. |
| Artifact path | Confirm `RECOMMENDER_STORE_PATH` points at the intended ignored SQLite artifact. | App starts without reading raw IMDb TSV files at request time. |
| Shutdown | Stop `runserver` and any tunnel process. | Preview is no longer reachable. |

Observed local fixture smoke for this change:

| Check | Result |
| --- | --- |
| Fixture artifact build | `make imdb-bootstrap ARGS="--sample --output-dir data/imdb-sample"`, `make canonical-dataset ...`, and `python recommender.py ... "Sample Movie"` completed; recommender returned `['Sample Sequel']`. |
| `make smoke` | Passed with `System check identified no issues (0 silenced).` |
| HTTP preview smoke | `runserver` on `127.0.0.1:8765` served the homepage with HTTP 200 and a CSRF token. |
| Recommendation request | CSRF-protected POST for `Sample Movie` returned HTTP 200 and included `Sample Sequel`. |
