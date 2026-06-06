"""Tests for the uz-kit setup tool's data-driven CLI-tool registry.

Runs under a bare `python3` (no rich needed): _ui degrades to a plain-print
shim and _cli_tools imports rich only inside audit_table.
"""
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.join(_HERE, "..", "tools")
_INSTALLER = os.path.join(_TOOLS, "installer")
sys.path.insert(0, _INSTALLER)
sys.path.insert(0, _TOOLS)

import register as reg  # noqa: E402
import shell as sh  # noqa: E402
import model as mdl  # noqa: E402
import paths as pth  # noqa: E402
import custom as cst  # noqa: E402
import strategies as strat  # noqa: E402
import engine as eng  # noqa: E402

MANIFEST_NEW = os.path.join(_INSTALLER, "registry.toml")    # unified [[tool]] registry
ROOT = reg.plugin_root()


class RegisterCodexTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.dest = __import__("pathlib").Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_first_sync_creates_links(self):
        counts = reg.sync_codex(ROOT, dest=self.dest)
        self.assertGreater(counts["created"], 0)
        # a known command and a known skill should be linked
        self.assertTrue((self.dest / "review-spec.md").is_symlink())
        self.assertTrue((self.dest / "reviewing-specs.md").is_symlink())
        self.assertTrue((self.dest / "review-spec.md").resolve().exists())

    def test_second_sync_is_idempotent(self):
        first = reg.sync_codex(ROOT, dest=self.dest)
        second = reg.sync_codex(ROOT, dest=self.dest)
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["updated"], 0)
        self.assertEqual(second["removed"], 0)
        self.assertEqual(second["kept"], first["created"])

    def test_stale_uzkit_link_is_pruned(self):
        reg.sync_codex(ROOT, dest=self.dest)
        stale = self.dest / "not-a-real-asset.md"
        stale.symlink_to(ROOT / "README.md")          # points into uz-kit, not wanted
        counts = reg.sync_codex(ROOT, dest=self.dest)
        self.assertEqual(counts["removed"], 1)
        self.assertFalse(stale.exists())

    def test_foreign_link_is_left_alone(self):
        reg.sync_codex(ROOT, dest=self.dest)
        foreign_target = __import__("pathlib").Path(self._tmp.name) / "_foreign_source.md"
        foreign_target.write_text("user's own prompt")
        foreign = self.dest / "my-own-prompt.md"
        foreign.symlink_to(foreign_target)            # NOT pointing into uz-kit
        reg.sync_codex(ROOT, dest=self.dest)
        self.assertTrue(foreign.is_symlink())          # untouched


class RegisterClaudeTests(unittest.TestCase):
    def setUp(self):
        import tempfile, pathlib
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = pathlib.Path(self._tmp.name)

    def test_native_layout_links(self):
        reg.sync_claude(ROOT, dest=self.base)
        # command as a flat .md, skill as a whole directory symlink
        cmd = self.base / "commands" / "review-spec.md"
        skill = self.base / "skills" / "reviewing-specs"
        self.assertTrue(cmd.is_symlink() and cmd.resolve().exists())
        self.assertTrue(skill.is_symlink())
        self.assertTrue((skill / "SKILL.md").exists())   # links the dir, not just SKILL.md

    def test_idempotent(self):
        first = reg.sync_claude(ROOT, dest=self.base)
        second = reg.sync_claude(ROOT, dest=self.base)
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["updated"], 0)
        self.assertEqual(second["kept"], first["created"])

    def test_existing_relative_link_is_kept_not_rewritten(self):
        # mimic the user's existing relative symlink; sync must treat it as 'kept'.
        (self.base / "commands").mkdir(parents=True)
        target = (ROOT / "commands" / "review-spec.md").resolve()
        rel = os.path.relpath(target, self.base / "commands")
        (self.base / "commands" / "review-spec.md").symlink_to(rel)
        counts = reg.sync_claude(ROOT, dest=self.base)
        self.assertGreaterEqual(counts["kept"], 1)

    def test_real_file_is_not_clobbered(self):
        (self.base / "commands").mkdir(parents=True)
        real = self.base / "commands" / "review-spec.md"
        real.write_text("my own command")
        reg.sync_claude(ROOT, dest=self.base)
        self.assertFalse(real.is_symlink())
        self.assertIn("my own command", real.read_text())

    def test_stale_uzkit_link_pruned_foreign_kept(self):
        reg.sync_claude(ROOT, dest=self.base)
        stale = self.base / "skills" / "ghost"
        stale.symlink_to(ROOT / "skills" / "reviewing-specs")   # ours, not wanted name
        foreign_src = self.base / "_foreign"
        foreign_src.mkdir()
        foreign = self.base / "skills" / "mine"
        foreign.symlink_to(foreign_src)                          # not into uz-kit
        reg.sync_claude(ROOT, dest=self.base)
        self.assertFalse(stale.exists())                         # pruned
        self.assertTrue(foreign.is_symlink())                    # kept


class ShellGuardTests(unittest.TestCase):
    def setUp(self):
        import tempfile, pathlib
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = pathlib.Path(self._tmp.name)

    # ── PATH shims (universal ban) ──────────────────────────────────────────────
    def test_install_shims_creates_executable_failing_stubs(self):
        res = sh.install_shims(self.home)
        self.assertEqual(set(res), {"npm", "pip", "pip3"})
        npm = self.home / ".local" / "bin" / "npm"
        self.assertTrue(npm.exists())
        self.assertTrue(os.access(npm, os.X_OK))
        body = npm.read_text()
        self.assertIn(sh.SHIM_SENTINEL, body)
        self.assertIn(f"exit {sh.EXIT_CODE}", body)   # non-zero, fails the caller
        self.assertNotEqual(sh.EXIT_CODE, 0)

    def test_shims_are_idempotent(self):
        sh.install_shims(self.home)
        res = sh.install_shims(self.home)
        self.assertTrue(all(v == "refreshed" for v in res.values()))

    def test_shims_never_clobber_a_real_binary(self):
        d = self.home / ".local" / "bin"
        d.mkdir(parents=True)
        (d / "npm").write_text("#!/bin/sh\necho real npm\n")   # no sentinel → not ours
        res = sh.install_shims(self.home)
        self.assertTrue(res["npm"].startswith("skipped"))
        self.assertIn("real npm", (d / "npm").read_text())     # untouched

    def test_remove_shims_only_removes_ours(self):
        d = self.home / ".local" / "bin"
        d.mkdir(parents=True)
        (d / "pip").write_text("#!/bin/sh\necho real pip\n")   # foreign
        sh.install_shims(self.home)                            # creates npm, pip3; skips pip
        res = sh.remove_shims(self.home)
        self.assertEqual(res["npm"], "removed")
        self.assertEqual(res["pip"], "absent")                 # not ours → left alone
        self.assertTrue((d / "pip").exists())

    def test_targets_zsh_and_bash_by_default(self):
        targets = {p.name for p in sh.target_rc_files(self.home)}
        self.assertEqual(targets, {".zshrc", ".bashrc"})

    def test_unified_rc_takes_precedence(self):
        (self.home / ".shellrc").write_text("# mine\n")
        self.assertEqual([p.name for p in sh.target_rc_files(self.home)], [".shellrc"])
        (self.home / ".myshellrc").write_text("# mine\n")          # wins over .shellrc
        self.assertEqual([p.name for p in sh.target_rc_files(self.home)], [".myshellrc"])

    def test_install_adds_block_and_aliases(self):
        res = sh.install_ban_aliases(self.home)
        self.assertTrue(all(v == "added" for v in res.values()))
        body = (self.home / ".zshrc").read_text()
        self.assertIn(sh.BEGIN, body)
        self.assertIn("alias npm=", body)
        self.assertIn("alias pip=", body)

    def test_install_is_idempotent(self):
        sh.install_ban_aliases(self.home)
        sh.install_ban_aliases(self.home)                          # twice
        body = (self.home / ".zshrc").read_text()
        self.assertEqual(body.count(sh.BEGIN), 1)                  # exactly one block

    def test_install_preserves_existing_content(self):
        rc = self.home / ".zshrc"
        rc.write_text("export FOO=bar\n")
        sh.install_ban_aliases(self.home)
        self.assertIn("export FOO=bar", rc.read_text())

    def test_remove_round_trips_to_original(self):
        rc = self.home / ".zshrc"
        rc.write_text("export FOO=bar\n")
        sh.install_ban_aliases(self.home)
        sh.remove_ban_aliases(self.home)
        body = rc.read_text()
        self.assertNotIn(sh.BEGIN, body)
        self.assertIn("export FOO=bar", body)

    def test_remove_when_absent_is_noop(self):
        (self.home / ".zshrc").write_text("export FOO=bar\n")
        res = sh.remove_ban_aliases(self.home)
        self.assertEqual(res[str(self.home / ".zshrc")], "absent")


class ModelTests(unittest.TestCase):
    def test_minimal_row_defaults(self):
        t = mdl.Tool(id="rg", name="ripgrep", kind="pkg", category="search")
        self.assertEqual(t.cmd, "rg")          # cmd defaults to id
        self.assertEqual(t.priority, "P3")
        self.assertEqual(t.requires, [])
        self.assertEqual(t.pkg, {})

    def test_loader_parses_kinds_and_version_block(self):
        import tempfile, pathlib
        toml = (
            '[[tool]]\n'
            'id="lazygit"\nkind="github-release"\ncategory="git"\npriority="P2"\n'
            'repo="jesseduffield/lazygit"\nasset="lazygit_{ver}_Linux_{arch.suffix}.tar.gz"\n'
            'member="lazygit"\nbin_dir="~/.local/bin"\n'
            '[tool.version]\n'
            'latest="github:jesseduffield/lazygit"\n'
            'installed_cmd="lazygit --version"\ninstalled_re="version=(\\\\S+)"\n'
        )
        p = pathlib.Path(tempfile.mkdtemp()) / "r.toml"
        p.write_text(toml)
        tools = mdl.load_tools(p)
        self.assertEqual(len(tools), 1)
        t = tools[0]
        self.assertEqual(t.kind, "github-release")
        self.assertEqual(t.cmd, "lazygit")
        self.assertEqual(t.repo, "jesseduffield/lazygit")
        self.assertEqual(t.version_latest, "github:jesseduffield/lazygit")
        self.assertEqual(t.version_re, r"version=(\S+)")


class UnifiedManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tools = mdl.load_tools(MANIFEST_NEW)

    def test_loads_and_ids_unique(self):
        ids = [t.id for t in self.tools]
        self.assertGreater(len(ids), 25)
        self.assertEqual(len(ids), len(set(ids)), "duplicate tool ids")

    def test_every_kind_is_known(self):
        for t in self.tools:
            self.assertIn(t.kind, mdl.KINDS, f"{t.id}: bad kind {t.kind}")

    def test_kind_required_fields(self):
        for t in self.tools:
            if t.kind == "pkg":
                self.assertTrue(t.pkg.get("debian") or t.pkg.get("arch") or t.pkg.get("brew"), t.id)
            if t.kind == "cargo":
                self.assertTrue(t.crate, t.id)
            if t.kind == "node":
                self.assertTrue(t.npm_pkg, t.id)
            if t.kind == "curl":
                self.assertTrue(t.url or t.brew, t.id)
            if t.kind == "github-release":
                self.assertTrue(t.repo and t.asset, t.id)
            if t.kind == "marketplace":
                self.assertTrue(t.marketplace and t.marketplace_ref, t.id)
            if t.kind == "launcher":
                self.assertTrue(t.bootstrap_curl or t.bootstrap_brew or t.cmd, t.id)
            if t.kind == "custom":
                self.assertTrue(t.fn, t.id)

    def test_requires_reference_real_ids(self):
        ids = {t.id for t in self.tools}
        for t in self.tools:
            for dep in t.requires:
                self.assertIn(dep, ids, f"{t.id} requires unknown {dep}")

    def test_ai_launchers_present(self):
        ids = {t.id for t in self.tools}
        self.assertTrue({"gentle-ai", "gsd", "superpowers", "agent-toolkit"} <= ids)

    def test_gentle_ai_wiring_excludes_pi(self):
        g = next(t for t in self.tools if t.id == "gentle-ai")
        self.assertIn("--agent", g.wiring)
        self.assertNotIn("pi", g.wiring.split("--agent")[1].split("--")[0])

    def test_pnpm_has_setup_command(self):
        p = next(t for t in self.tools if t.id == "pnpm")
        self.assertEqual(p.setup, "pnpm self-update && pnpm setup")

    def test_pi_requires_node_and_orders_after_it(self):
        import engine as _eng
        pi = next(t for t in self.tools if t.id == "pi")
        self.assertIn("node", pi.requires)
        node = next(t for t in self.tools if t.id == "node")
        volta = next(t for t in self.tools if t.id == "volta")
        out = [t.id for t in _eng.order_for_install([pi, node, volta])]
        self.assertLess(out.index("node"), out.index("pi"))
        self.assertLess(out.index("volta"), out.index("node"))


class EngineStatusTests(unittest.TestCase):
    def _bin(self, name, body):
        import tempfile, pathlib
        d = tempfile.mkdtemp(); self.addCleanup(__import__("shutil").rmtree, d)
        p = pathlib.Path(d) / name; p.write_text("#!/bin/sh\n" + body); p.chmod(0o755)
        old = os.environ["PATH"]; os.environ["PATH"] = d + os.pathsep + old
        self.addCleanup(lambda: os.environ.__setitem__("PATH", old)); return name

    def test_missing_binary(self):
        t = mdl.Tool(id="nope-xyz", name="x", kind="pkg", category="extras")
        self.assertEqual(eng.status(t, "debian"), "missing")

    def test_installed_binary(self):
        n = self._bin("fakeok", 'echo 1.2.3\nexit 0\n')
        t = mdl.Tool(id=n, name="x", kind="curl", category="extras")
        self.assertEqual(eng.status(t, "debian"), "installed")

    def test_broken_volta_shim_is_missing(self):
        n = self._bin("fakepnpm", 'echo \'Volta error: Could not find executable "fakepnpm"\' >&2\nexit 1\n')
        t = mdl.Tool(id=n, name="x", kind="custom", category="pkg-mgr", fn="install_pnpm")
        self.assertEqual(eng.status(t, "debian"), "missing")

    def test_launcher_unwired_when_marker_absent(self):
        t = mdl.Tool(id="x", name="x", kind="launcher", category="ai", cmd="sh",
                     wired_marker="/nonexistent/marker")
        self.assertEqual(eng.status(t, "debian"), "unwired")

    def test_npx_launcher_unknown(self):
        t = mdl.Tool(id="gsd", name="gsd", kind="launcher", category="ai", cmd="npx")
        self.assertEqual(eng.status(t, "debian"), "unknown")


class EngineOrderTests(unittest.TestCase):
    def _t(self, i, req=None):
        return mdl.Tool(id=i, name=i, kind="pkg", category="x", requires=req or [])

    def test_topo_order(self):
        a = self._t("pyright", ["volta"]); v = self._t("volta")
        out = [t.id for t in eng.order_for_install([a, v])]
        self.assertLess(out.index("volta"), out.index("pyright"))

    def test_drag_in_missing_dependency(self):
        catalogue = [self._t("pyright", ["volta"]), self._t("volta")]
        dragged = eng.with_required([catalogue[0]], catalogue, lambda t: t.id != "volta")
        self.assertEqual({t.id for t in dragged}, {"pyright", "volta"})

    def test_drag_in_skips_already_installed_dep(self):
        catalogue = [self._t("pyright", ["volta"]), self._t("volta")]
        dragged = eng.with_required([catalogue[0]], catalogue, lambda t: True)
        self.assertEqual({t.id for t in dragged}, {"pyright"})


class EngineInstallSetupTests(unittest.TestCase):
    def test_setup_command_runs_after_install(self):
        import strategies
        calls = []
        orig_strat = strategies.STRATEGIES.copy()
        orig_run = eng.subprocess.run
        # make the strategy a no-op and capture the sh -c setup invocation
        strategies.STRATEGIES["pkg"] = lambda t, o, a: None
        eng.subprocess.run = lambda *a, **k: calls.append(a[0]) or __import__("types").SimpleNamespace(returncode=0)
        self.addCleanup(lambda: strategies.STRATEGIES.update(orig_strat))
        self.addCleanup(lambda: setattr(eng.subprocess, "run", orig_run))
        t = mdl.Tool(id="pnpm", name="pnpm", kind="pkg", category="pkg-mgr",
                     setup="pnpm self-update && pnpm setup")
        eng.install(t, "debian", {})
        self.assertTrue(any(c == ["sh", "-c", "pnpm self-update && pnpm setup"] for c in calls))


class SyncTests(unittest.TestCase):
    def setUp(self):
        self._orig_latest = eng.paths_latest_version
        self._orig_iv = eng._installed_version
        self.addCleanup(lambda: setattr(eng, "paths_latest_version", self._orig_latest))
        self.addCleanup(lambda: setattr(eng, "_installed_version", self._orig_iv))

    def test_sync_row_skips_without_version_block(self):
        t = mdl.Tool(id="bat", name="bat", kind="pkg", category="nav")
        self.assertEqual(eng.sync_row(t)["state"], "skip")

    def test_sync_row_outdated(self):
        eng.paths_latest_version = lambda src: ("0.45.0", "2026-05-20")
        eng._installed_version = lambda tool: "0.44.1"
        t = mdl.Tool(id="sh", name="lazygit", kind="github-release", category="git",
                     version_latest="github:jesseduffield/lazygit")
        row = eng.sync_row(t)        # cmd 'sh' is on PATH so it's considered present
        self.assertEqual(row["latest"], "0.45.0")
        self.assertEqual(row["latest_date"], "2026-05-20")
        self.assertEqual(row["state"], "outdated")

    def test_sync_row_ok_when_equal(self):
        eng.paths_latest_version = lambda src: ("0.20.1", "2026-04-11")
        eng._installed_version = lambda tool: "0.20.1"
        t = mdl.Tool(id="sh", name="eza", kind="github-release", category="nav",
                     version_latest="github:eza-community/eza")
        self.assertEqual(eng.sync_row(t)["state"], "ok")


class StrategyTests(unittest.TestCase):
    def setUp(self):
        self._run, self._cmd_ok, self._latest = strat._run, strat._cmd_ok, strat._latest
        self.addCleanup(lambda: setattr(strat, "_run", self._run))
        self.addCleanup(lambda: setattr(strat, "_cmd_ok", self._cmd_ok))
        self.addCleanup(lambda: setattr(strat, "_latest", self._latest))

    def test_dispatch_covers_every_kind(self):
        for t in mdl.load_tools(MANIFEST_NEW):
            self.assertIn(t.kind, strat.STRATEGIES, f"no strategy for kind {t.kind}")

    def test_curl_builds_installer_command(self):
        calls = []
        strat._run = lambda c: calls.append(c)
        t = mdl.Tool(id="uv", name="uv", kind="curl", category="pkg-mgr",
                     url="https://astral.sh/uv/install.sh", shell="sh", bin_dir="~/.local/bin")
        strat.install_curl(t, "debian", {})
        self.assertTrue(any("astral.sh/uv/install.sh" in " ".join(c) for c in calls))

    def test_github_release_raw_downloads_binary(self):
        calls = []
        strat._run = lambda c: calls.append(c)
        strat._latest = lambda repo: ("4.0.0", "2026-01-01")
        t = mdl.Tool(id="yq", name="yq", kind="github-release", category="data",
                     repo="mikefarah/yq", asset="yq_linux_{arch.deb}", raw=True,
                     bin_dir="~/.local/bin")
        strat.install_github_release(t, "debian", {"deb": "amd64", "go": "amd64", "suffix": "x86_64"})
        joined = " ".join(" ".join(c) for c in calls)
        self.assertIn("yq_linux_amd64", joined)

    def test_node_uses_volta_or_pnpm_never_npm(self):
        calls = []
        strat._run = lambda c: calls.append(c)
        strat._cmd_ok = lambda c: c[0] == "volta"
        t = mdl.Tool(id="pyright", cmd="pyright-langserver", name="pyright", kind="node",
                     category="lsp", npm_pkg="pyright")
        strat.install_node(t, "debian", {})
        self.assertEqual(calls, [["volta", "install", "pyright"]])

    def test_node_raises_when_no_volta_or_pnpm(self):
        strat._run = lambda c: None
        strat._cmd_ok = lambda c: False
        t = mdl.Tool(id="x", name="x", kind="node", category="lsp", npm_pkg="x")
        with self.assertRaises(RuntimeError) as e:
            strat.install_node(t, "debian", {})
        self.assertIn("npm", str(e.exception).lower())


class CustomFnTests(unittest.TestCase):
    def test_every_custom_row_has_a_fn(self):
        for t in mdl.load_tools(MANIFEST_NEW):
            if t.kind == "custom":
                self.assertTrue(hasattr(cst, t.fn), f"missing {t.fn} for {t.id}")


class PathReminderFromRegistryTests(unittest.TestCase):
    def test_bin_dirs_collected_from_registry(self):
        import importlib, pathlib
        wiz = importlib.import_module("setup")
        dirs = wiz.bin_dirs(mdl.load_tools(MANIFEST_NEW))
        self.assertIn(str(pathlib.Path("~/.local/bin").expanduser()), dirs)
        self.assertTrue(any(".volta" in d for d in dirs))


class PathsTests(unittest.TestCase):
    def test_ensure_on_path_creates_and_prepends(self):
        import tempfile, pathlib
        d = pathlib.Path(tempfile.mkdtemp()) / "newbin"
        old = os.environ["PATH"]
        self.addCleanup(lambda: os.environ.__setitem__("PATH", old))
        pth.ensure_on_path(d)
        self.assertTrue(d.is_dir())
        self.assertTrue(os.environ["PATH"].startswith(str(d) + os.pathsep))

    def test_ensure_on_path_is_idempotent(self):
        import tempfile, pathlib
        d = pathlib.Path(tempfile.mkdtemp())
        old = os.environ["PATH"]
        self.addCleanup(lambda: os.environ.__setitem__("PATH", old))
        pth.ensure_on_path(d)
        pth.ensure_on_path(d)
        self.assertEqual(os.environ["PATH"].count(str(d)), 1)

    def test_render_asset_template(self):
        arch = {"deb": "amd64", "go": "amd64", "suffix": "x86_64"}
        out = pth.render_asset("lazygit_{ver}_{os}_{arch.suffix}.tar.gz",
                               ver="0.45.0", os_token="Linux", arch=arch, machine="x86_64")
        self.assertEqual(out, "lazygit_0.45.0_Linux_x86_64.tar.gz")


class NoBareNpmTests(unittest.TestCase):
    """Node packages go through volta/pnpm only — never bare npm; Python via uv, never pip."""

    def test_install_node_never_falls_back_to_npm(self):
        # already covered behaviourally in StrategyTests; assert the error mentions the ban
        orig_ok, orig_run = strat._cmd_ok, strat._run
        strat._cmd_ok = lambda c: False
        strat._run = lambda c: None
        try:
            t = mdl.Tool(id="x", name="x", kind="node", category="lsp", npm_pkg="x")
            with self.assertRaises(RuntimeError) as e:
                strat.install_node(t, "debian", {})
            self.assertIn("npm", str(e.exception).lower())
        finally:
            strat._cmd_ok, strat._run = orig_ok, orig_run

    def test_no_npm_or_pip_invocation_in_installer_source(self):
        import pathlib
        banned = ['"npm",', '"npm"]', "npm install", "npm add",
                  '"pip",', '"pip"]', '"pip3"', "pip install"]
        installer = pathlib.Path(_INSTALLER)
        for py in installer.glob("*.py"):
            if py.name == "shell.py":          # its whole job is to name+ban npm/pip
                continue
            for ln in py.read_text().splitlines():
                code = ln.split("#", 1)[0]     # ignore comments
                for bad in banned:
                    self.assertNotIn(bad, code, f"{py.name}: {ln.strip()}")


if __name__ == "__main__":
    unittest.main()
