"""Release orchestration safety boundaries, without network or remote writes."""
from pathlib import Path
from unittest.mock import Mock, patch
import json
import tempfile
import unittest

import yaml

from scripts import release_cut as cut


CHANGELOG = """# Changelog

## [Unreleased]

Target release: `0.3.28`

### Breaking changes

- None.

### Fixed

- A consumer fix.

## [0.3.27] - 2026-10-16

### Breaking changes

- None.
"""
PROJECT = '[project]\nname = "example"\nversion = "0.3.28"\n\n[tool.example]\nversion = "leave-me"\n'


class TransformTests(unittest.TestCase):
    def test_prepare_preserves_history_and_advances_target(self):
        result = cut.prepare_changelog(CHANGELOG, "0.3.28", "2026-10-17")
        self.assertIn('Target release: `0.3.29`', result)
        self.assertIn('## [0.3.28] - 2026-10-17\n\n### Breaking changes', result)
        self.assertEqual(result.split('## [0.3.27]')[1], CHANGELOG.split('## [0.3.27]')[1])
        self.assertEqual(result.count('- A consumer fix.'), 1)

    def test_refuse_empty_mismatch_duplicate_and_invalid_date(self):
        cases = [
            (CHANGELOG.replace('- A consumer fix.', ''), '0.3.28', '2026-10-17'),
            (CHANGELOG, '0.3.29', '2026-10-17'),
            (CHANGELOG + '\n## [0.3.28] - 2026-10-17\n', '0.3.28', '2026-10-17'),
            (CHANGELOG, '0.3.28', '2026-02-30'),
        ]
        for args in cases:
            with self.subTest(args=args), self.assertRaises(ValueError):
                cut.prepare_changelog(*args)

    def test_patch_has_no_arbitrary_decimal_rollover(self):
        self.assertEqual(cut.next_version('1.9.99'), '1.9.100')
        for invalid in ('01.2.3', '1.2', '1.2.3rc1', '1.2.3\n', '; touch file'):
            with self.subTest(version=invalid), self.assertRaises(cut.CutError):
                cut.next_version(invalid)

    def test_train_changes_only_project_version_and_checks_target(self):
        prepared = cut.prepare_changelog(CHANGELOG, '0.3.28', '2026-10-17')
        self.assertEqual(cut.open_train_text(PROJECT, prepared, '0.3.28'),
                         PROJECT.replace('0.3.28', '0.3.29'))
        with self.assertRaises(cut.CutError):
            cut.open_train_text(PROJECT, CHANGELOG, '0.3.28')
        with self.assertRaises(cut.CutError):
            cut.require_version('0.3.29', '0.3.28')

    def test_stage_boundaries(self):
        cases = [
            (('M', None, None, None, 'M'), 'prepare'),
            (('M', 'A', None, None, 'M'), 'promote'),
            (('A', 'A', None, None, 'M'), 'tag'),
            (('A', 'A', None, 'A', 'M'), 'open-train'),
            (('A', 'A', 'B', 'A', 'M'), 'open-train'),
            (('B', 'A', 'B', 'A', 'M'), 'done'),
        ]
        for args, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(cut.detect_stage(*args), expected)
        for args in [('M', 'A', None, 'elsewhere', 'M'),
                     ('moved', 'A', None, None, 'M'),
                     ('moved', 'A', 'B', 'A', 'M'),
                     ('B', 'A', 'B', None, 'M')]:
            with self.subTest(args=args), self.assertRaises(cut.CutError):
                cut.detect_stage(*args)


class CandidateTests(unittest.TestCase):
    def test_train_tree_replay_rejects_extra_content_and_wrong_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = cut.Repository(Path(directory))
            repo.git('init', '-q')
            repo.git('config', 'user.name', 'Test')
            repo.git('config', 'user.email', 'test@example.invalid')
            repo.write('pyproject.toml', PROJECT)
            repo.write('CHANGELOG.md', cut.prepare_changelog(CHANGELOG, '0.3.28', '2026-10-17'))
            repo.git('add', '.')
            repo.git('commit', '-qm', 'base')
            base = repo.git('rev-parse', 'HEAD')
            repo.train('0.3.28')
            train = repo.commit('open-train', '0.3.28')
            repo.validate_candidate(train, 'open-train', '0.3.28', base)
            repo.write('extra.txt', 'unexpected content')
            repo.git('add', 'extra.txt')
            repo.git('commit', '--amend', '--no-edit', '-q')
            tampered = repo.git('rev-parse', 'HEAD')
            with self.assertRaisesRegex(cut.CutError, 'tree differs'):
                repo.validate_candidate(tampered, 'open-train', '0.3.28', base)
            with self.assertRaisesRegex(cut.CutError, 'single parent'):
                repo.validate_candidate(tampered, 'open-train', '0.3.28', train)

    def test_prepare_does_not_replace_lock_and_calls_only_generators(self):
        repo = cut.Repository()
        old = {'0.3.27': 'old-digest'}
        repo.read = Mock(side_effect=[CHANGELOG, json.dumps({'sections': old})])
        repo.write = Mock()
        repo.python = Mock(side_effect=['ok', json.dumps({**old, '0.3.28': 'new-digest'}), 'ok', 'ok'])
        repo.prepare_files('0.3.28', '2026-10-17')
        written = json.loads(repo.write.call_args_list[1].args[1])
        self.assertEqual(written['sections'], {**old, '0.3.28': 'new-digest'})
        self.assertEqual(repo.python.call_args_list[-1].args, ('scripts/refresh_validation_harnesses.py',))
        repo.read.side_effect = [CHANGELOG, json.dumps({'sections': old})]
        repo.python.side_effect = ['ok', json.dumps({'0.3.27': 'changed', '0.3.28': 'new'})]
        with self.assertRaisesRegex(cut.CutError, 'old release digests'):
            repo.prepare_files('0.3.28', '2026-10-17')


class FakeRepository:
    """Observable refs, with injectable races/failures; never invokes git/gh."""
    def __init__(self, main='M', prep=None, train=None, tag=None):
        self.main = main
        self.prep = prep
        self.train_sha = train
        self.tag = tag
        self.commands = []
        self.local_head = main
        self.fail_push = False

    def git(self, *args):
        self.commands.append(args)
        if args == ('status', '--porcelain'):
            return ''
        if args[:1] == ('checkout',):
            self.local_head = args[-1]
        if args[:1] == ('show',):
            sha = args[-1]
            return {'A': 'Release cut: prepare 0.3.28',
                    'B': 'Release cut: open-train 0.3.28'}.get(sha, 'ordinary change')
        if args[:1] == ('rev-parse',):
            return 'M'
        if args[:1] == ('push',):
            if self.fail_push:
                raise cut.CutError('push rejected')
            if args[-1].endswith(':refs/heads/main'):
                self.main = args[-1].split(':')[0]
        return ''

    def refresh(self):
        return self.main

    def ref(self, name):
        if name.endswith('/prepare'):
            return self.prep
        if name.endswith('/open-train'):
            return self.train_sha
        return self.tag

    def read(self, path):
        return PROJECT.replace('0.3.28', '0.3.29') if self.main == 'B' else PROJECT

    def prepare(self, *args):
        self.commands.append(('prepare',))

    def train(self, *args):
        self.commands.append(('train',))

    def checks(self):
        self.commands.append(('checks',))

    def commit(self, stage, *args):
        return 'A' if stage == 'prepare' else 'B'

    def validate_candidate(self, *args):
        self.commands.append(('validate', *args))


ENV = {'GITHUB_REF': 'refs/heads/main', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
       'GITHUB_REPOSITORY': 'owner/repo', 'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '2'}


@patch.dict('os.environ', ENV)
class OrchestrationTests(unittest.TestCase):
    def execute(self, repo, dry=False, effect=None):
        with patch.object(cut, 'Actions') as actions, patch.object(cut, 'summary'), patch.object(cut, 'cleanup') as cleanup:
            actions.return_value.wait.side_effect = effect
            cut.orchestrate(repo, '', dry)
            return actions.return_value.wait.call_args_list, cleanup

    def test_fresh_run_promotes_only_after_each_ci_and_release(self):
        repo = FakeRepository()
        calls, _ = self.execute(repo)
        self.assertEqual([(c.args[0], c.args[3]) for c in calls],
                         [('ci.yml', 'workflow_dispatch'), ('ci.yml', 'push'),
                          ('release.yml', 'push'), ('ci.yml', 'workflow_dispatch')])
        pushes = [c[-1] for c in repo.commands if c[0] == 'push']
        self.assertEqual(pushes, ['A:refs/heads/release-cut/v0.3.28/prepare',
                                 'A:refs/heads/main', 'refs/tags/v0.3.28',
                                 'B:refs/heads/release-cut/v0.3.28/open-train', 'B:refs/heads/main'])

    def test_resume_after_promotion_does_not_prepare_or_promote_again(self):
        repo = FakeRepository(main='A', prep='A')
        calls, _ = self.execute(repo)
        self.assertEqual(calls[0].args, ('ci.yml', 'main', 'A', 'push'))
        self.assertNotIn(('prepare',), repo.commands)
        self.assertNotIn(('push', 'origin', 'A:refs/heads/main'), repo.commands)

    def test_resume_tag_and_train_and_done(self):
        for main, train in [('A', None), ('A', 'B'), ('B', 'B')]:
            with self.subTest(main=main, train=train):
                repo = FakeRepository(main=main, prep='A', train=train, tag='A')
                self.execute(repo)
                self.assertFalse(any(c[0] == 'push' and c[-1].startswith('refs/tags/') for c in repo.commands))
                if main == 'B':
                    self.assertFalse(any(c[0] == 'push' for c in repo.commands))

    def test_failed_dispatch_cannot_promote_or_tag(self):
        repo = FakeRepository()
        with self.assertRaises(cut.CutError):
            self.execute(repo, effect=cut.CutError('CI failed'))
        self.assertEqual([c for c in repo.commands if c[0] == 'push'],
                         [('push', 'origin', 'A:refs/heads/release-cut/v0.3.28/prepare')])

    def test_rejected_main_push_stops_before_tag(self):
        repo = FakeRepository(prep='A')
        repo.fail_push = True
        with self.assertRaises(cut.CutError):
            self.execute(repo)
        self.assertFalse(any('tag' in c for c in repo.commands))

    def test_race_during_release_prevents_train(self):
        repo = FakeRepository(main='A', prep='A', tag='A')
        def wait(workflow, *_args, **_kwargs):
            if workflow == 'release.yml':
                repo.main = 'unexpected'
            return 'https://example.invalid/run'
        with self.assertRaisesRegex(cut.CutError, 'main moved after tag'):
            self.execute(repo, effect=wait)
        self.assertNotIn(('train',), repo.commands)

    def test_dry_run_checks_train_and_cleans_after_success_or_failure(self):
        for failure in [False, True]:
            repo = FakeRepository()
            with patch.object(cut, 'Actions') as actions, patch.object(cut, 'cleanup') as cleanup, patch.object(cut, 'summary'):
                if failure:
                    actions.return_value.wait.side_effect = cut.CutError('CI failed')
                    with self.assertRaises(cut.CutError):
                        cut.orchestrate(repo, '', True)
                else:
                    cut.orchestrate(repo, '', True)
                    self.assertIn(('train',), repo.commands)
                cleanup.assert_called_once_with(repo, 'release-cut/dry-run/123-2')
                pushes = [c for c in repo.commands if c[0] == 'push']
                self.assertEqual(pushes, [('push', 'origin', 'A:refs/heads/release-cut/dry-run/123-2')])

    def test_non_main_and_cleanup_scope_fail_closed(self):
        with patch.dict('os.environ', {'GITHUB_REF': 'refs/heads/other'}), self.assertRaises(cut.CutError):
            cut.orchestrate(FakeRepository(), '', False)
        with self.assertRaises(cut.CutError):
            cut.cleanup(FakeRepository(), 'main')


@patch.dict('os.environ', ENV)
class ActionsTests(unittest.TestCase):
    def test_selection_filters_event_branch_sha_even_if_api_does_not(self):
        actions = cut.Actions(Mock())
        good = {'id': 1, 'head_sha': 'A', 'head_branch': 'main', 'event': 'push'}
        actions.api = Mock(return_value={'workflow_runs': [good, {**good, 'id': 2, 'event': 'workflow_dispatch'},
                                                          {**good, 'id': 3, 'head_sha': 'other'}]})
        self.assertEqual(actions.find('ci.yml', 'main', 'A', 'push'), good)

    def test_wait_requires_unique_ci_required_not_just_run_success(self):
        run = {'id': 1, 'head_sha': 'A', 'head_branch': 'branch', 'event': 'workflow_dispatch',
               'status': 'completed', 'conclusion': 'success', 'html_url': 'https://example.invalid/1'}
        for jobs in [[], [{'name': 'ci-required', 'conclusion': 'skipped'}],
                     [{'name': 'ci-required', 'conclusion': 'success'}] * 2]:
            actions = cut.Actions(Mock())
            actions.find = Mock(return_value=run)
            actions.api = Mock(side_effect=[run, {'total_count': len(jobs), 'jobs': jobs}])
            with self.subTest(jobs=jobs), self.assertRaises(cut.CutError):
                actions.wait('ci.yml', 'branch', 'A', 'workflow_dispatch', dispatch=True)
            actions.repo.run.assert_not_called()

    def test_discovery_is_bounded_and_does_not_repeat_dispatch(self):
        actions = cut.Actions(Mock())
        actions.find = Mock(return_value=None)
        with patch.object(cut.time, 'sleep') as sleep, self.assertRaisesRegex(cut.CutError, '10 minutes'):
            actions.wait('ci.yml', 'branch', 'A', 'workflow_dispatch', dispatch=True)
        self.assertEqual(sleep.call_count, 20)
        actions.repo.run.assert_called_once()

    def test_watch_is_bounded_and_failed_run_never_auto_redispatched(self):
        for status in ['queued', 'completed']:
            actions = cut.Actions(Mock())
            run = {'id': 1, 'head_sha': 'A', 'head_branch': 'main', 'event': 'push',
                   'status': status, 'conclusion': 'failure', 'html_url': 'https://example.invalid/1'}
            actions.find = Mock(return_value=run)
            actions.api = Mock(return_value={**run, 'status': 'completed'})
            with self.assertRaises(cut.CutError):
                actions.wait('ci.yml', 'main', 'A', 'push')
            if status == 'queued':
                self.assertEqual(actions.repo.run.call_args.kwargs['timeout'], 5400)
                self.assertIn('30', actions.repo.run.call_args.args)
            else:
                actions.repo.run.assert_not_called()


class WorkflowTests(unittest.TestCase):
    def test_workflow_credentials_triggers_and_pins(self):
        root = Path(__file__).resolve().parents[1]
        # BaseLoader preserves YAML's Actions `on` key without YAML 1.1 booleans.
        workflow = yaml.load((root / '.github/workflows/release-cut.yml').read_text(encoding='utf-8'), Loader=yaml.BaseLoader)
        self.assertEqual(set(workflow['on']), {'workflow_dispatch'})
        self.assertEqual(workflow['permissions'], {})
        self.assertEqual(workflow['concurrency']['cancel-in-progress'], 'false')
        job = workflow['jobs']['cut']
        self.assertEqual(job['environment'], 'release')
        self.assertEqual(job['permissions'], {'contents': 'read', 'actions': 'write'})
        self.assertEqual(job['if'], "github.ref == 'refs/heads/main'")
        checkout = next(step for step in job['steps'] if step.get('uses', '').startswith('actions/checkout@'))
        self.assertEqual(checkout['with']['ssh-key'], '${{ secrets.RELEASE_DEPLOY_KEY }}')
        existing = (root / '.github/workflows/ci.yml').read_text(encoding='utf-8')
        for step in job['steps']:
            if 'uses' in step:
                self.assertIn(step['uses'], existing)
        self.assertEqual(job['steps'][-1]['if'], 'always() && inputs.dry_run')
