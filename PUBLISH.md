# Publishing to PyPI

Owner steps for releasing `base64hub` on [PyPI](https://pypi.org/project/base64hub/). Nothing here runs
automatically. This file is not part of the sdist or the wheel.

## 1. Account (once)

1. Register at https://pypi.org/account/register/ as user `base64hub` with `g@base64hub.com`
   and verify the email.
2. Turn on two-factor authentication (TOTP app or security key). PyPI requires it before uploads
   and API tokens. Store the recovery codes.
3. Optional dry run: the same on https://test.pypi.org/ (separate account and tokens).
4. Check the name is still free: https://pypi.org/project/base64hub/ should return 404.

## 2. Pre-release checks

Run in a full clone of the repo:

```sh
python3 -m unittest
git log --format='%an <%ae>' | sort -u
git log --format='%cn <%ce>' | sort -u
```

Both `git log` lines must print only `base64hub <g@base64hub.com>`. Also run the identity grep
from the Identity section of the internal software contract over the tree and over `dist/` after
the build; it must print nothing.

Version: `1.0.0` lives in two places, `pyproject.toml` and `src/base64hub/__init__.py`. Change both
for a new release; PyPI never accepts the same version twice, even after a delete.

## 3. Build

Tools from apt, no downloads from PyPI:

```sh
sudo apt-get install python3-build flit twine
rm -rf dist
python3 -m build --no-isolation
unzip -l dist/base64hub-*.whl
tar tzf dist/base64hub-*.tar.gz
twine check dist/*
```

Check the wheel holds only `base64hub/*.py`, `base64hub/py.typed`, the license and metadata, and that
`twine check` passes (it renders README.md the way PyPI will).

Smoke test the wheel in a throwaway venv:

```sh
python3 -m venv /tmp/b64-check
/tmp/b64-check/bin/pip install --no-index dist/base64hub-*.whl
/tmp/b64-check/bin/b64 "Hello, hub!"
rm -rf /tmp/b64-check
```

## 4. Upload with an API token

1. PyPI, Account settings, API tokens, "Add API token". The project does not exist before the first
   upload, so the first token has to be scoped to the whole account.
2. Upload, giving the token only to this command (no file on disk):

   ```sh
   TWINE_USERNAME=__token__ TWINE_PASSWORD='pypi-...' twine upload dist/*
   ```

   Without the apt `twine`, a throwaway venv works too, nothing installed globally:
   `python3 -m venv /tmp/twine && /tmp/twine/bin/pip install twine && /tmp/twine/bin/twine upload dist/*`,
   then `rm -rf /tmp/twine`.
3. Right after the first upload: create a new token scoped to project `base64hub` only, delete the
   account-wide one, and use the project token for later releases.
4. Check https://pypi.org/project/base64hub/: README rendering, the four project links, author
   `base64hub`, license MIT. Then `pipx install base64hub` on a clean machine and `b64 -v`.

## 5. Later: trusted publishing

Once https://github.com/base64hub-com/base64hub-python is public, switch to token-free releases from GitHub Actions:

1. PyPI, project `base64hub`, Publishing, add a GitHub trusted publisher: owner `base64hub`,
   repository `python`, workflow `release.yml`, environment `pypi`.
2. In the repo, create the `pypi` environment (Settings, Environments) and a workflow
   `.github/workflows/release.yml` that runs on a published release: check out, run
   `python3 -m unittest`, `python3 -m build`, then the `pypa/gh-action-pypi-publish` action pinned
   to a commit SHA, with `permissions: id-token: write` on that job only.
3. Delete the remaining API token from PyPI.

## 6. After the release

- Fill the PyPI link (`https://pypi.org/project/base64hub/`) in the site's `data/apps.yaml` so the
  buttons on `/pypi/` and `/download/` appear.
- Tag the release in git: `git tag v1.0.0`.
