# Publishing to PyPI

SynapseCTRL is published from GitHub Actions using [uv](https://docs.astral.sh/uv/) and PyPI Trusted Publishing. No long-lived PyPI API token is stored in the repository.

The release workflow is intentionally **manual**. Nothing is published on a normal push or pull request.

## Trusted Publisher configuration

The PyPI Trusted Publisher must match the repository workflow exactly:

| Setting | Value |
| --- | --- |
| PyPI project | `SynapseCTRL` |
| GitHub owner | `gabrielzv1233` |
| Repository | `SynapseCTRL` |
| Workflow | `publish.yml` |
| Environment | `pypi` |

The workflow lives at `.github/workflows/publish.yml`.

## Release flow

### 1. Choose the version

The package version is stored in `pyproject.toml`.

With uv, a normal patch bump is:

```powershell
uv version --bump patch
```

Or set an explicit version:

```powershell
uv version 0.2.1
```

Commit and push the version change before publishing.

### 2. Run the normal validation locally

```powershell
uv sync
uv run python -m unittest discover -s tests -v
uv run python -m compileall -q src examples
uv build
```

### 3. Run the publish workflow

On GitHub:

1. Open **Actions**.
2. Select **Publish to PyPI**.
3. Click **Run workflow**.
4. Choose the `main` branch.
5. Run it.

The workflow then:

1. runs the full unit suite on Windows
2. validates the native hook installer
3. builds the wheel and source distribution with `uv build`
4. smoke-tests the built package and installed CLI
5. verifies the packaged hook installer exists inside the wheel
6. generates PyPI attestations
7. publishes with `uv publish` using Trusted Publishing

If any validation step fails, the publish job does not run.

## First release

For a pending Trusted Publisher, the first successful trusted publish creates the PyPI project. The project name is normalized for installation, so users install it as:

```powershell
pip install synapsectrl
```

or:

```powershell
uv tool install synapsectrl
```

The installed console command is:

```powershell
synapsectrl
```

## Do not reuse versions

PyPI does not allow replacing an already-published distribution version. If a release needs a fix, bump the version and publish again.

For example, after `0.2.0` has been published:

```powershell
uv version 0.2.1
```

Do not delete and recreate a release just to reuse the same version number.
