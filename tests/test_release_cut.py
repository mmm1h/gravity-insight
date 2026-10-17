"""Release orchestration safety boundaries, without network or remote writes."""
from pathlib import Path
from unittest.mock import Mock, patch
import json
import re
import subprocess
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


class LeaseTestCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        env = patch.dict('os.environ', {'RUNNER_TEMP': directory.name})
        env.start()
        self.addCleanup(env.stop)


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
        if args[:1] == ('show',) and args[-1].endswith(':pyproject.toml'):
            return PROJECT.replace('0.3.28', '0.3.29') if args[-1].split(':')[0] in {'B', 'C'} else PROJECT
        if args[:1] == ('show',):
            sha = args[-1]
            return {'A': 'Release cut: prepare 0.3.28',
                    'B': 'Release cut: open-train 0.3.28'}.get(sha, 'ordinary change')
        if args[:1] == ('log',):
            return 'A\tRelease cut: prepare 0.3.28' if self.main in {'A', 'advanced'} else ''
        if args[:1] == ('rev-parse',):
            return 'M'
        if args[:1] == ('push',):
            if self.fail_push:
                raise cut.CutError('push rejected')
            if args[-1].endswith(':refs/heads/main'):
                self.main = args[-1].split(':')[0]
            elif args[-1].endswith('/prepare'):
                self.prep = args[-1].split(':')[0] or None
            elif args[-1].endswith('/open-train'):
                self.train_sha = args[-1].split(':')[0] or None
            elif args[-1].startswith('refs/tags/'):
                self.tag = 'A'
        return ''

    def remote_tag(self, version):
        return self.tag

    def ancestor(self, older, newer):
        return older == 'M' or older == newer or (older == 'A' and newer in {'B', 'C', 'advanced'})

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
       'GITHUB_SHA': 'M', 'GITHUB_REPOSITORY': 'owner/repo', 'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '2'}


@patch.dict('os.environ', ENV)
class OrchestrationTests(LeaseTestCase):
    def execute(self, repo, dry=False, effect=None):
        with patch.object(cut, 'Actions') as actions, patch.object(cut, 'summary'), patch.object(cut, 'cleanup') as cleanup:
            actions.return_value.wait.side_effect = effect
            cut.orchestrate(repo, '', dry)
            return actions.return_value.wait.call_args_list, cleanup

    def test_fresh_run_promotes_only_after_each_ci_and_release(self):
        repo = FakeRepository()
        calls, _ = self.execute(repo)
        self.assertEqual([(c.args[0], c.args[3]) for c in calls],
                         [('ci.yml', 'push'), ('ci.yml', 'push'),
                          ('release.yml', 'push'), ('ci.yml', 'push')])
        pushes = [c[-1] for c in repo.commands if c[0] == 'push']
        self.assertEqual(pushes, ['A:refs/heads/release-cut/v0.3.28/prepare',
                                 'A:refs/heads/main', 'refs/tags/v0.3.28',
                                 'B:refs/heads/release-cut/v0.3.28/open-train', 'B:refs/heads/main',
                                 ':refs/heads/release-cut/v0.3.28/prepare',
                                 ':refs/heads/release-cut/v0.3.28/open-train'])

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

    def test_failed_candidate_push_ci_cannot_promote_or_tag(self):
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
class CandidatePushTests(LeaseTestCase):
    """Exercise real Actions/Repository.run down to the subprocess boundary."""

    def execute(self, repo, *, dry=False, missing_sha=None):
        repo.root = cut.ROOT
        repo.run = lambda *args, **kwargs: cut.Repository.run(repo, *args, **kwargs)
        queries, runs = [], {}

        def boundary(command, **kwargs):
            self.assertEqual(kwargs['encoding'], 'utf-8')
            self.assertEqual(command[0], 'gh')
            self.assertNotEqual(command[1:3], ['workflow', 'run'])
            if command[1:3] == ['run', 'watch']:
                self.assertIn(int(command[3]), runs)
                return subprocess.CompletedProcess(command, 0, stdout='')
            self.assertEqual(command[1:4], ['api', '--method', 'GET'])
            path = command[4]
            if '/workflows/' in path:
                fields = dict(value.split('=', 1) for flag, value in
                              zip(command[5::2], command[6::2]) if flag == '-f')
                workflow = path.split('/workflows/')[1].split('/')[0]
                query = (workflow, fields['branch'], fields['head_sha'], fields['event'])
                queries.append(query)
                self.assertEqual(fields['event'], 'push')
                run_id = len(queries)
                run = dict(id=run_id, head_sha=fields['head_sha'], head_branch=fields['branch'],
                           event='push', status='queued', conclusion=None, html_url=f'url/{run_id}')
                runs[run_id] = {**run, 'status': 'completed', 'conclusion': 'success'}
                # Even a newer successful dispatch on the same SHA must never count.
                inventory = [{**run, 'id': run_id + 1000, 'event': 'workflow_dispatch',
                              'status': 'completed', 'conclusion': 'success'}]
                if fields['head_sha'] != missing_sha:
                    inventory.append(run)
                result = dict(total_count=len(inventory), workflow_runs=inventory)
            elif path.endswith('/jobs'):
                result = dict(total_count=1, jobs=[dict(name='ci-required', conclusion='success')])
            else:
                result = runs[int(path.rsplit('/', 1)[1])]
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(result))

        with patch.object(cut.subprocess, 'run', side_effect=boundary), \
                patch.object(cut.Actions, 'require_unpublished'), \
                patch.object(cut, 'cleanup'), patch.object(cut, 'summary'), \
                patch.object(cut.time, 'sleep') as sleep:
            try:
                cut.orchestrate(repo, '', dry)
            finally:
                self.queries = queries
                self.sleeps = sleep.call_count
        return queries

    def test_all_candidate_waits_use_push_at_subprocess_boundary(self):
        full = self.execute(FakeRepository())
        dry = self.execute(FakeRepository(), dry=True)
        self.assertEqual(full, [
            ('ci.yml', 'release-cut/v0.3.28/prepare', 'A', 'push'),
            ('ci.yml', 'main', 'A', 'push'),
            ('release.yml', 'v0.3.28', 'A', 'push'),
            ('ci.yml', 'release-cut/v0.3.28/open-train', 'B', 'push')])
        self.assertEqual(dry, [('ci.yml', 'release-cut/dry-run/123-2', 'A', 'push')])

    def test_ci_push_trigger_covers_every_pushed_candidate_ref(self):
        workflow = yaml.load((cut.ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8'),
                             Loader=yaml.BaseLoader)
        patterns = workflow['on']['push']['branches']
        branches = set()
        for dry in (False, True):
            repo = FakeRepository()
            self.execute(repo, dry=dry)
            for command in repo.commands:
                if command[0] == 'push' and ':refs/heads/' in command[-1]:
                    sha, ref = command[-1].split(':', 1)
                    if sha and ref != 'refs/heads/main':
                        branches.add(ref.removeprefix('refs/heads/'))
        self.assertEqual(len(branches), 3)
        # GitHub * excludes '/', while ** includes nested candidate names.
        for branch in branches:
            covered = False
            for pattern in patterns:
                regex = re.escape(pattern.removeprefix('!')).replace(r'\*\*', '.*').replace(r'\*', '[^/]*')
                if re.fullmatch(regex, branch):
                    covered = not pattern.startswith('!')  # Ordered exclusions can undo inclusion.
            self.assertTrue(covered, (branch, patterns))

    def test_unpromoted_candidate_without_push_ci_is_replaced_after_main_advances(self):
        repo = FakeRepository(main='new-base', prep='old-A')
        queries = self.execute(repo, missing_sha='old-A')
        self.assertIn(('push', 'origin',
                       '--force-with-lease=refs/heads/release-cut/v0.3.28/prepare:old-A',
                       'A:refs/heads/release-cut/v0.3.28/prepare'), repo.commands)
        self.assertEqual(queries[0], ('ci.yml', 'release-cut/v0.3.28/prepare', 'A', 'push'))
        self.assertFalse(any(query[2] == 'old-A' for query in queries))

    def test_existing_candidate_without_push_ci_stops_with_exact_lease_recovery(self):
        repo = FakeRepository(prep='A')
        with self.assertRaises(cut.CutError) as failure:
            self.execute(repo, missing_sha='A')
        message = str(failure.exception)
        self.assertIn('no ci.yml push run for release-cut/v0.3.28/prepare@A after 10 minutes', message)
        self.assertIn('git push origin --force-with-lease=refs/heads/release-cut/v0.3.28/prepare:A '
                      ':refs/heads/release-cut/v0.3.28/prepare; then retry', message)
        self.assertIn('advanced main regenerates an unpromoted prepare candidate automatically', message)
        self.assertEqual(self.sleeps, 20)
        self.assertEqual(len(self.queries), 21)
        self.assertFalse(any(command[0] in {'prepare', 'push', 'tag'} for command in repo.commands))


@patch.dict('os.environ', ENV)
class ActionsTests(unittest.TestCase):
    def test_selection_filters_event_branch_sha_even_if_api_does_not(self):
        actions = cut.Actions(Mock())
        good = {'id': 1, 'head_sha': 'A', 'head_branch': 'main', 'event': 'push',
                'status': 'completed', 'conclusion': 'success', 'html_url': 'url/1'}
        actions.api = Mock(return_value={'total_count': 3, 'workflow_runs': [good, {**good, 'id': 2, 'event': 'workflow_dispatch'},
                                                          {**good, 'id': 3, 'head_sha': 'other'}]})
        self.assertEqual(actions.find('ci.yml', 'main', 'A', 'push'), good)

    def test_wait_requires_unique_ci_required_not_just_run_success(self):
        run = {'id': 1, 'head_sha': 'A', 'head_branch': 'branch', 'event': 'push',
               'status': 'completed', 'conclusion': 'success', 'html_url': 'https://example.invalid/1'}
        for jobs in [[], [{'name': 'ci-required', 'conclusion': 'skipped'}],
                     [{'name': 'ci-required', 'conclusion': 'success'}] * 2]:
            actions = cut.Actions(Mock())
            actions.find = Mock(return_value=run)
            actions.api = Mock(side_effect=[run, {'total_count': len(jobs), 'jobs': jobs}])
            with self.subTest(jobs=jobs), self.assertRaises(cut.CutError):
                actions.wait('ci.yml', 'branch', 'A', 'push')
            actions.repo.run.assert_not_called()

    def test_discovery_is_bounded_and_never_dispatches(self):
        actions = cut.Actions(Mock())
        actions.find = Mock(return_value=None)
        with patch.object(cut.time, 'sleep') as sleep, self.assertRaisesRegex(cut.CutError, '10 minutes'):
            actions.wait('ci.yml', 'branch', 'A', 'push')
        self.assertEqual(sleep.call_count, 20)
        actions.repo.run.assert_not_called()

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
        self.assertEqual(job['permissions'], {'contents': 'read', 'actions': 'read'})
        self.assertEqual(job['if'], "github.ref == 'refs/heads/main'")
        checkout = next(step for step in job['steps'] if step.get('uses', '').startswith('actions/checkout@'))
        self.assertEqual(checkout['with']['ssh-key'], '${{ secrets.RELEASE_DEPLOY_KEY }}')
        existing = (root / '.github/workflows/ci.yml').read_text(encoding='utf-8')
        for step in job['steps']:
            if 'uses' in step:
                self.assertIn(step['uses'], existing)
        self.assertEqual(job['steps'][-1]['if'], 'always() && inputs.dry_run')


@patch.dict('os.environ', ENV)
class RecoveryTests(LeaseTestCase):
    execute = OrchestrationTests.execute

    def test_old_retry_after_later_commit_or_deleted_candidates_pushes_nothing(self):
        for main in ('B', 'C'):
            for requested in ('', '0.3.28'):
                repo = FakeRepository(main=main, tag='A')
                with patch.object(cut, 'Actions') as actions, patch.object(cut, 'summary') as summary:
                    cut.orchestrate(repo, requested, False)
                self.assertEqual(actions.return_value.method_calls, [])
                self.assertEqual(summary.call_args.args[0],
                    f'Release cut 0.3.28 done; publication record: '
                    f'https://github.com/{actions.return_value.slug}/actions/workflows/release.yml?query=branch%3Av0.3.28')
                self.assertFalse(any(c[0] == 'push' for c in repo.commands))

    def test_absent_tag_and_changed_version_requires_new_dispatch(self):
        with self.assertRaisesRegex(cut.CutError, 'dispatch a new cut'):
            self.execute(FakeRepository(main='C'))

    def test_stale_prep_uses_lease_and_new_sha_ci(self):
        repo = FakeRepository(main='new-base', prep='old-A')
        calls, _ = self.execute(repo)
        self.assertIn(('push', 'origin', '--force-with-lease=refs/heads/release-cut/v0.3.28/prepare:old-A',
                       'A:refs/heads/release-cut/v0.3.28/prepare'), repo.commands)
        self.assertEqual(calls[0].args[2], 'A')

    def test_promoted_prep_is_not_regenerated(self):
        repo = FakeRepository(main='advanced', prep='A')
        with self.assertRaisesRegex(cut.CutError, 'main_advanced_after_promotion'):
            self.execute(repo)
        self.assertFalse(any(c[0] in {'prepare', 'push'} for c in repo.commands))

    def test_main_races_after_promotion_and_during_train_ci(self):
        for boundary in ('push', 'train'):
            repo = FakeRepository()
            def wait(workflow, branch, sha, event, **kwargs):
                if (boundary == 'push' and branch == 'main' and workflow == 'ci.yml'
                        or boundary == 'train' and branch.endswith('/open-train')):
                    repo.main = 'advanced'
            with self.assertRaisesRegex(cut.CutError, 'main_advanced_after_promotion|refusing train'):
                self.execute(repo, effect=wait)
            self.assertNotIn(('push', 'origin', 'B:refs/heads/main'), repo.commands)
            if boundary == 'push':
                self.assertIsNone(repo.tag)

    def test_race_between_last_refresh_and_tag_push_preserves_tag_and_stops(self):
        repo = FakeRepository()
        original = repo.git
        def git(*args):
            result = original(*args)
            if args == ('push', 'origin', 'refs/tags/v0.3.28'):
                repo.main = 'advanced'
            return result
        repo.git = git
        with self.assertRaisesRegex(cut.CutError, 'main moved after tag'):
            self.execute(repo)
        self.assertEqual(repo.tag, 'A')
        self.assertNotIn(('train',), repo.commands)

    def test_lost_acknowledgement_after_each_push_resumes_remote_state(self):
        targets = ['A:refs/heads/release-cut/v0.3.28/prepare', 'A:refs/heads/main',
                   'refs/tags/v0.3.28', 'B:refs/heads/release-cut/v0.3.28/open-train',
                   'B:refs/heads/main']
        for target in targets:
            with self.subTest(target=target):
                repo = FakeRepository()
                original = repo.git
                def git(*args):
                    result = original(*args)
                    if args[0] == 'push' and args[-1] == target:
                        raise subprocess.CalledProcessError(128, ['git', *args], stderr='connection lost')
                    return result
                repo.git = git
                with self.assertRaises(subprocess.CalledProcessError):
                    self.execute(repo)
                repo.git = original
                repo.commands.clear()
                self.execute(repo)
                self.assertEqual(repo.main, 'B')
                self.assertFalse(any(c[0] == 'push' and c[-1] == target for c in repo.commands))

    def test_stale_train_rebuilt_with_lease(self):
        repo = FakeRepository(main='A', prep='A', tag='A', train='old-B')
        validate = repo.validate_candidate
        def replay(sha, *args):
            if sha == 'old-B':
                raise cut.CutError('candidate must have exactly the expected single parent')
            validate(sha, *args)
        repo.validate_candidate = replay
        self.execute(repo)
        self.assertIn(('push', 'origin', '--force-with-lease=refs/heads/release-cut/v0.3.28/open-train:old-B',
                       'B:refs/heads/release-cut/v0.3.28/open-train'), repo.commands)

    def test_dry_failures_always_attempt_cleanup(self):
        for method in ('prepare', 'checks', 'train', 'commit'):
            with self.subTest(method=method):
                repo = FakeRepository()
                setattr(repo, method, Mock(side_effect=cut.CutError(method)))
                with patch.object(cut, 'Actions'), patch.object(cut, 'cleanup') as cleanup:
                    with self.assertRaises(cut.CutError):
                        cut.orchestrate(repo, '', True)
                    if method in {'prepare', 'commit'}:
                        cleanup.assert_not_called()
                    else:
                        cleanup.assert_called_once_with(repo, 'release-cut/dry-run/123-2')
                self.assertFalse(any(c[0] == 'push' and ('main' in c[-1] or 'tags/' in c[-1]) for c in repo.commands))

    def test_cleanup_failure_is_best_effort_with_exact_leases(self):
        repo = FakeRepository()
        original = repo.git
        deletions = []
        def git(*args):
            if args[0] == 'push' and args[-1].startswith(':'):
                deletions.append(args)
                raise subprocess.CalledProcessError(1, ['git', *args])
            return original(*args)
        repo.git = git
        self.execute(repo)
        self.assertEqual(repo.main, 'B')
        self.assertEqual(deletions, [
            ('push', 'origin', '--force-with-lease=refs/heads/release-cut/v0.3.28/prepare:A',
             ':refs/heads/release-cut/v0.3.28/prepare'),
            ('push', 'origin', '--force-with-lease=refs/heads/release-cut/v0.3.28/open-train:B',
             ':refs/heads/release-cut/v0.3.28/open-train')])

    def test_remote_tag_changes_during_release_stop_train(self):
        for tag in (None, 'elsewhere'):
            repo = FakeRepository(main='A', prep='A', tag='A')
            def wait(workflow, *args, **kwargs):
                if workflow == 'release.yml':
                    repo.tag = tag
            with self.assertRaisesRegex(cut.CutError, 'remote tag missing or changed'):
                self.execute(repo, effect=wait)
            self.assertNotIn(('train',), repo.commands)


@patch.dict('os.environ', ENV)
class ReadFailureTests(unittest.TestCase):
    def test_newer_failed_run_beats_older_successful_rerun(self):
        actions = cut.Actions(Mock())
        older = dict(id=1, head_sha='A', head_branch='main', event='push',
                     status='completed', conclusion='success', html_url='url/1', run_attempt=5)
        newer = {**older, 'id': 2, 'conclusion': 'failure', 'html_url': 'url/2', 'run_attempt': 1}
        actions.api = Mock(side_effect=[{'total_count': 2, 'workflow_runs': [older, newer]}, newer])
        with self.assertRaisesRegex(cut.CutError, 'run 2 url/2 conclusion=failure'):
            actions.wait('ci.yml', 'main', 'A', 'push')

    def test_real_watch_error_reports_final_state_and_recovery(self):
        actions = cut.Actions(Mock())
        run = dict(id=42, head_sha='A', head_branch='main', event='push',
                   status='in_progress', conclusion=None, html_url='url/42')
        actions.find = Mock(return_value=run)
        actions.repo.run.side_effect = subprocess.CalledProcessError(1, ['gh', 'run', 'watch'], stderr='failed')
        actions.api = Mock(return_value={**run, 'status': 'completed', 'conclusion': 'failure'})
        with self.assertRaisesRegex(cut.CutError, 'run 42 url/42 conclusion=failure; re-run failed jobs, then retry the cut'):
            actions.wait('ci.yml', 'main', 'A', 'push')

    def test_api_retries_transient_only_and_bounds_exhaustion(self):
        for error, attempts in [('HTTP 503', 3), ('HTTP 502', 3), ('HTTP 429', 3), ('connection reset', 3),
                                ('HTTP/2 403: network access denied', 1), ('HTTP/1.1 502', 3),
                                ('HTTP/2 429', 3), ('HTTP 403: network access denied', 1), ('HTTP 401', 1), ('HTTP 403', 1), ('HTTP 422', 1)]:
            repo = Mock()
            repo.run.side_effect = subprocess.CalledProcessError(1, ['gh', 'api'], stderr=error)
            with patch.object(cut.time, 'sleep') as sleep, self.assertRaises(subprocess.CalledProcessError):
                cut.Actions(repo).api('actions/runs/1')
            self.assertEqual(repo.run.call_count, attempts)
            self.assertTrue(all(call.args[1:4] == ('api', '--method', 'GET')
                                for call in repo.run.call_args_list))
            self.assertEqual([c.args[0] for c in sleep.call_args_list], [1, 2] if attempts == 3 else [])
        repo.run.side_effect = [subprocess.CalledProcessError(1, ['gh'], stderr='HTTP 502'), '{"ok": true}']
        with patch.object(cut.time, 'sleep'):
            self.assertEqual(cut.Actions(repo).api('read'), {'ok': True})

    def test_oversized_job_inventory_fails_closed(self):
        actions = cut.Actions(Mock())
        run = dict(id=1, head_sha='A', head_branch='main', event='push',
                   status='completed', conclusion='success', html_url='url')
        actions.find = Mock(return_value=run)
        actions.api = Mock(side_effect=[run, {'total_count': 101, 'jobs': [{'name': 'ci-required', 'conclusion': 'success'}]}])
        with self.assertRaisesRegex(cut.CutError, 'unique successful'):
            actions.wait('ci.yml', 'main', 'A', 'push')

    def test_any_publication_evidence_forbids_tag_creation(self):
        absent = subprocess.CalledProcessError(1, ['gh'], stderr='HTTP 404')
        for evidence in ('run', 'release', 'pypi', 'auth'):
            actions = cut.Actions(Mock())
            runs = {'total_count': 1 if evidence == 'run' else 0, 'workflow_runs': []}
            actions.api = Mock(side_effect=[runs, {} if evidence == 'release' else
                (subprocess.CalledProcessError(1, ['gh'], stderr='HTTP 403') if evidence == 'auth' else absent)])
            with patch.object(cut, 'pypi_exists', return_value=evidence == 'pypi'), self.assertRaises((cut.CutError, subprocess.CalledProcessError)):
                actions.require_unpublished('0.3.28')
            self.assertNotIn('head_sha', str(actions.api.call_args_list[0]))

    def test_pypi_missing_published_transient_and_invalid_reads(self):
        from urllib.error import HTTPError, URLError
        for error, result, count in [(HTTPError('url', 404, '', {}, None), False, 1),
                                     (HTTPError('url', 503, '', {}, None), None, 3),
                                     (URLError('offline'), None, 3)]:
            with patch.object(cut.urllib.request, 'urlopen', side_effect=error) as request, patch.object(cut.time, 'sleep'):
                if result is False:
                    self.assertFalse(cut.pypi_exists('0.3.28'))
                else:
                    with self.assertRaises(cut.CutError):
                        cut.pypi_exists('0.3.28')
                self.assertEqual(request.call_count, count)
        for body in (b'{}', b'broken'):
            response = Mock()
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            response.read.return_value = body
            with patch.object(cut.urllib.request, 'urlopen', return_value=response):
                if body == b'{}':
                    self.assertTrue(cut.pypi_exists('0.3.28'))
                else:
                    with self.assertRaises(cut.CutError):
                        cut.pypi_exists('0.3.28')


class GitReplayTests(unittest.TestCase):
    def make_repo(self, directory):
        repo = cut.Repository(Path(directory))
        repo.git('init', '-q')
        repo.git('config', 'user.name', 'Test')
        repo.git('config', 'user.email', 'test@example.invalid')
        repo.write('pyproject.toml', PROJECT)
        repo.write('CHANGELOG.md', CHANGELOG)
        (repo.root / 'scripts').mkdir()
        repo.write('scripts/changelog_release_lock.json', '{"sections": {"0.3.27": "old"}}')
        repo.git('add', '.')
        repo.git('commit', '-qm', 'base')
        return repo

    def test_prepare_replays_recorded_date_and_rejects_tampering_without_ref_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = self.make_repo(directory)
            base = repo.git('rev-parse', 'HEAD')
            # Generator outputs are isolated; real preparation, lock update, git trees,
            # commit metadata, detach/reset and date parsing execute unchanged.
            repo.python = Mock(side_effect=lambda *args: json.dumps({'0.3.27': 'old', '0.3.28': 'new'})
                               if '--print-digests' in args else '')
            repo.prepare_files('0.3.28', '2026-10-17')
            prep = repo.commit('prepare', '0.3.28', '2026-10-17')
            with patch.object(cut, 'datetime') as clock:
                clock.now.side_effect = AssertionError('replay must not read today')
                repo.validate_candidate(prep, 'prepare', '0.3.28', base)
            for mutation in ('content', 'missing-date', 'invalid-date'):
                repo.git('checkout', '--detach', prep)
                if mutation == 'content':
                    repo.write('pyproject.toml', PROJECT + '\n# altered code\n')
                    repo.git('add', '.')
                    repo.git('commit', '--amend', '--no-edit', '-q')
                else:
                    repo.git('commit', '--amend', '-qm', 'Release cut: prepare 0.3.28', '-m',
                             '' if mutation == 'missing-date' else 'Release-Cut-Date: 2026-02-30')
                rejected = repo.git('rev-parse', 'HEAD')
                refs = repo.git('show-ref')
                with self.assertRaises(ValueError):
                    repo.validate_candidate(rejected, 'prepare', '0.3.28', base)
                self.assertEqual(repo.git('show-ref'), refs)
                self.assertEqual(repo.git('status', '--porcelain'), '')

    def test_authoritative_remote_tag_ignores_retained_local_tag_and_detects_recreation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'local').mkdir()
            repo = self.make_repo(root / 'local')
            remote = cut.Repository(root / 'remote.git')
            remote.root.mkdir()
            remote.git('init', '--bare', '-q')
            repo.git('remote', 'add', 'origin', str(remote.root))
            first = repo.git('rev-parse', 'HEAD')
            repo.git('tag', 'v0.3.28')
            repo.git('push', '-q', 'origin', 'refs/tags/v0.3.28')
            self.assertEqual(repo.remote_tag('0.3.28'), first)
            remote.git('update-ref', '-d', 'refs/tags/v0.3.28')
            self.assertEqual(repo.ref('refs/tags/v0.3.28'), first)
            self.assertIsNone(repo.remote_tag('0.3.28'))
            repo.git('commit', '--allow-empty', '-qm', 'later')
            later = repo.git('rev-parse', 'HEAD')
            repo.git('push', '-q', 'origin', f'{later}:refs/tags/v0.3.28')
            self.assertEqual(repo.remote_tag('0.3.28'), later)

    def test_dry_cleanup_push_failure_and_restricted_ref(self):
        repo = Mock()
        ref = 'refs/heads/release-cut/dry-run/123-2'
        sha = 'a' * 40
        repo.git.side_effect = [f'{sha}\t{ref}',
                                subprocess.CalledProcessError(128, ['git', 'push'])]
        with self.assertRaisesRegex(cut.CutError, 'cleanup failed.*retained'):
            cut.cleanup(repo, 'release-cut/dry-run/123-2', expected_sha=sha)
        self.assertEqual(repo.git.call_args.args,
                         ('push', 'origin', f'--force-with-lease={ref}:{sha}', f':{ref}'))


@patch.dict('os.environ', ENV)
class AdditionalBoundaries(LeaseTestCase):
    def test_tag_seen_then_deleted_is_never_recreated_even_without_run_evidence(self):
        repo = FakeRepository(main='A', prep='A', tag='A')
        def wait(*args, **kwargs):
            repo.tag = None
        with self.assertRaisesRegex(cut.CutError, 'never recreate'):
            OrchestrationTests.execute(self, repo, effect=wait)
        self.assertFalse(any(c[0] == 'push' for c in repo.commands))

    def test_stale_candidate_with_publication_evidence_is_not_replaced(self):
        repo = FakeRepository(main='new-main', prep='old-A')
        with patch.object(cut, 'Actions') as actions:
            actions.return_value.require_unpublished.side_effect = cut.CutError('prior publication evidence')
            with self.assertRaisesRegex(cut.CutError, 'prior publication'):
                cut.orchestrate(repo, '', False)
        self.assertFalse(any(c[0] == 'push' for c in repo.commands))

    def test_dry_push_failure_still_cleans(self):
        repo = FakeRepository()
        repo.fail_push = True
        with patch.object(cut, 'Actions'), patch.object(cut, 'cleanup') as cleanup:
            with self.assertRaises(cut.CutError):
                cut.orchestrate(repo, '', True)
            cleanup.assert_called_once_with(repo, 'release-cut/dry-run/123-2')

    def test_watch_timeout_and_final_read_auth_failure_are_closed(self):
        run = dict(id=7, head_sha='A', head_branch='main', event='push',
                   status='queued', conclusion=None, html_url='url/7')
        for final in (run, subprocess.CalledProcessError(1, ['gh'], stderr='HTTP 401')):
            actions = cut.Actions(Mock())
            actions.find = Mock(return_value=run)
            actions.repo.run.side_effect = subprocess.TimeoutExpired(['gh', 'run', 'watch'], 5400)
            actions.api = Mock(side_effect=final) if isinstance(final, Exception) else Mock(return_value=final)
            with self.assertRaisesRegex(cut.CutError, '7.*url/7'):
                actions.wait('ci.yml', 'main', 'A', 'push')

    def test_fresh_dispatch_after_train_targets_new_empty_release(self):
        repo = FakeRepository(main='B', tag=None)
        repo.prepare = Mock(side_effect=cut.CutError('refusing empty release'))
        with patch.dict('os.environ', {'GITHUB_SHA': 'B'}), patch.object(cut, 'Actions'):
            with self.assertRaisesRegex(cut.CutError, 'empty release'):
                cut.orchestrate(repo, '', False)
        self.assertEqual(repo.prepare.call_args.args[0], '0.3.29')
        self.assertFalse(any(c[0] == 'push' for c in repo.commands))


@patch.dict('os.environ', ENV)
class RoundTwoTrustTests(LeaseTestCase):
    make_repo = GitReplayTests.make_repo

    def assert_untrusted_rejected_at_subprocess(self, tagged):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'local').mkdir()
            repo = self.make_repo(root / 'local')
            base = repo.git('rev-parse', 'HEAD')
            remote = cut.Repository(root / 'remote.git')
            remote.root.mkdir()
            remote.git('init', '--bare', '-q')
            repo.git('remote', 'add', 'origin', str(remote.root))
            repo.git('push', '-q', 'origin', f'{base}:refs/heads/main')
            repo.write('scripts/check_changelog.py', 'raise RuntimeError("foreign code executed")\n')
            repo.git('add', '.')
            repo.git('commit', '-qm', 'foreign parent')
            repo.git('commit', '--allow-empty', '-qm', 'Release cut: prepare 0.3.28',
                     '-m', 'Release-Cut-Date: 2026-10-17')
            candidate = repo.git('rev-parse', 'HEAD')
            ref = 'refs/tags/v0.3.28' if tagged else 'refs/heads/release-cut/v0.3.28/prepare'
            repo.git('push', '-q', 'origin', f'{candidate}:{ref}')
            repo.git('checkout', '--detach', base)
            real_run = subprocess.run
            commands = []
            def boundary(command, **kwargs):
                commands.append(command)
                # Fetch only reads the local fixture remote; all other allowed Git
                # operations are reads. Checkout/reset/push, gh, Python and pip fail here.
                self.assertEqual(command[0], 'git')
                self.assertIn(command[1], {'status', 'fetch', 'rev-parse', 'show',
                                          'ls-remote', 'merge-base', 'for-each-ref'})
                return real_run(command, **kwargs)
            reason = 'foreign_release_tag' if tagged else 'foreign_candidate_parent'
            with patch.dict('os.environ', {'GITHUB_SHA': base}), patch.object(
                    cut.subprocess, 'run', side_effect=boundary), self.assertRaisesRegex(cut.CutError, reason):
                cut.orchestrate(repo, '', False)
            fetch = next(i for i, c in enumerate(commands) if c[1:3] == ['fetch', '--prune'])
            ancestry = next(i for i, c in enumerate(commands) if c[1] == 'merge-base')
            self.assertLess(fetch, ancestry)
            self.assertEqual(remote.git('rev-parse', ref), candidate)

    def test_foreign_prepare_parent_rejected_before_any_executable_subprocess(self):
        self.assert_untrusted_rejected_at_subprocess(tagged=False)

    def test_tag_outside_main_rejected_before_any_executable_subprocess(self):
        self.assert_untrusted_rejected_at_subprocess(tagged=True)

    def test_train_parent_checked_before_checkout_or_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = self.make_repo(directory)
            base = repo.git('rev-parse', 'HEAD')
            repo.git('commit', '--allow-empty', '-qm', 'foreign train parent')
            repo.git('commit', '--allow-empty', '-qm', 'Release cut: open-train 0.3.28')
            train = repo.git('rev-parse', 'HEAD')
            real_run = subprocess.run
            commands = []
            def boundary(command, **kwargs):
                commands.append(command)
                self.assertEqual(command[:2], ['git', 'rev-list'])
                return real_run(command, **kwargs)
            with patch.object(cut.subprocess, 'run', side_effect=boundary), self.assertRaisesRegex(
                    cut.CutError, 'single parent'):
                repo.validate_candidate(train, 'open-train', '0.3.28', base)
            self.assertEqual(len(commands), 1)

    def test_missing_prep_ref_recovers_promoted_history_and_stops_if_advanced(self):
        for advanced in (False, True):
            with self.subTest(advanced=advanced), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / 'local').mkdir()
                repo = self.make_repo(root / 'local')
                base = repo.git('rev-parse', 'HEAD')
                repo.python = Mock(side_effect=lambda *args: json.dumps({'0.3.27': 'old', '0.3.28': 'new'})
                                   if '--print-digests' in args else '')
                repo.prepare_files('0.3.28', '2026-10-17')
                prep = repo.commit('prepare', '0.3.28', '2026-10-17')
                if advanced:
                    repo.git('commit', '--allow-empty', '-qm', 'ordinary C; version remains V')
                main = repo.git('rev-parse', 'HEAD')
                remote = cut.Repository(root / 'remote.git')
                remote.root.mkdir()
                remote.git('init', '--bare', '-q')
                repo.git('remote', 'add', 'origin', str(remote.root))
                repo.git('push', '-q', 'origin', f'{main}:refs/heads/main')
                # No prepare ref exists. Real history discovery and deterministic replay run.
                with patch.dict('os.environ', {'GITHUB_SHA': base}), patch.object(cut, 'Actions') as actions, \
                        patch.object(repo, 'git', wraps=repo.git) as git:
                    actions.return_value.wait.side_effect = cut.CutError('recovered main A; stop at CI')
                    reason = 'main_advanced_after_promotion.*forward-only' if advanced else 'recovered main A'
                    with self.assertRaisesRegex(cut.CutError, reason):
                        cut.orchestrate(repo, '', False)
                    self.assertFalse(any(c.args[0] == 'push' for c in git.call_args_list))
                    if advanced:
                        actions.return_value.wait.assert_not_called()
                    else:
                        actions.return_value.wait.assert_called_once_with('ci.yml', 'main', prep, 'push')

    def test_dry_cleanup_lease_race_preserves_remote_tip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'local').mkdir()
            repo = self.make_repo(root / 'local')
            before = repo.git('rev-parse', 'HEAD')
            remote = cut.Repository(root / 'remote.git')
            remote.root.mkdir()
            remote.git('init', '--bare', '-q')
            repo.git('remote', 'add', 'origin', str(remote.root))
            branch = 'release-cut/dry-run/123-2'
            ref = f'refs/heads/{branch}'
            repo.git('push', '-q', 'origin', f'{before}:{ref}')
            repo.git('commit', '--allow-empty', '-qm', 'replacement')
            after = repo.git('rev-parse', 'HEAD')
            repo.git('push', '-q', 'origin', f'{after}:refs/heads/object-source')
            original = repo.git
            commands = []
            def racing_git(*args):
                commands.append(args)
                value = original(*args)
                if args[0] == 'ls-remote':
                    remote.git('update-ref', ref, after, before)
                return value
            repo.git = racing_git
            with self.assertRaisesRegex(cut.CutError, 'cleanup failed.*retained'):
                cut.cleanup(repo, branch, expected_sha=before)
            self.assertIn(('push', 'origin', f'--force-with-lease={ref}:{before}', f':{ref}'), commands)
            self.assertEqual(remote.git('rev-parse', ref), after)

    def test_dry_cleanup_inside_run_keeps_pushed_sha_as_lease(self):
        repo = FakeRepository()
        prep = 'a' * 40
        replacement = 'b' * 40
        repo.commit = Mock(side_effect=[prep, 'train'])
        original = repo.git
        def git(*args):
            if args[0] == 'ls-remote':
                return f'{replacement}\trefs/heads/release-cut/dry-run/123-2'
            return original(*args)
        repo.git = git
        with patch.object(cut, 'Actions'), patch.object(cut, 'summary'), self.assertRaisesRegex(
                cut.CutError, 'lease mismatch.*retained'):
            cut.orchestrate(repo, '', True)
        self.assertEqual([c for c in repo.commands if c[0] == 'push'],
                         [('push', 'origin', f'{prep}:refs/heads/release-cut/dry-run/123-2')])


@patch.dict('os.environ', ENV)
class DecisionSchemaTests(unittest.TestCase):
    def test_publication_inventory_requires_valid_empty_evidence(self):
        malformed = [None, [], {}, {'total_count': 0}, {'workflow_runs': []},
                     {'total_count': None, 'workflow_runs': None},
                     {'total_count': False, 'workflow_runs': []},
                     {'total_count': -1, 'workflow_runs': []},
                     {'total_count': '0', 'workflow_runs': []},
                     {'total_count': 0.0, 'workflow_runs': []},
                     {'total_count': 0, 'workflow_runs': {}},
                     {'total_count': 0, 'workflow_runs': [dict(id=1)]}]
        for value in malformed:
            with self.subTest(value=value):
                actions = cut.Actions(Mock())
                actions.api = Mock(return_value=value)
                with patch.object(cut, 'pypi_exists') as pypi, self.assertRaisesRegex(cut.CutError, 'inventory schema'):
                    actions.require_unpublished('0.3.28')
                actions.api.assert_called_once()
                pypi.assert_not_called()
        for count, runs in [(1, []), (1, [{}])]:
            actions.api = Mock(return_value={'total_count': count, 'workflow_runs': runs})
            with self.assertRaisesRegex(cut.CutError, 'prior publication evidence'):
                actions.require_unpublished('0.3.28')
        actions.api = Mock(side_effect=[{'total_count': 0, 'workflow_runs': []},
            subprocess.CalledProcessError(1, ['gh'], stderr='HTTP 404')])
        with patch.object(cut, 'pypi_exists', return_value=False) as pypi:
            actions.require_unpublished('0.3.28')
        pypi.assert_called_once_with('0.3.28')

    def test_run_discovery_malformed_inventory_cannot_dispatch(self):
        run = dict(id=1, head_sha='A', head_branch='main', event='push',
                   status='completed', conclusion='success', html_url='url/1')
        values = [None, {}, {'total_count': 1, 'workflow_runs': []},
                  {'total_count': 0, 'workflow_runs': None},
                  {'total_count': 1, 'workflow_runs': [None]},
                  {'total_count': 1, 'workflow_runs': [{**run, 'id': True}]}]
        values += [{'total_count': 1, 'workflow_runs': [{k: v for k, v in run.items() if k != key}]}
                   for key in run]
        for value in values:
            with self.subTest(value=value):
                actions = cut.Actions(Mock())
                actions.api = Mock(return_value=value)
                with self.assertRaisesRegex(cut.CutError, 'schema'):
                    actions.wait('ci.yml', 'main', 'A', 'push')
                actions.repo.run.assert_not_called()

    def test_jobs_inventory_malformed_or_incomplete_cannot_authorize(self):
        run = dict(id=1, head_sha='A', head_branch='main', event='push',
                   status='completed', conclusion='success', html_url='url/1')
        good = dict(name='ci-required', conclusion='success')
        values = [None, {}, {'total_count': None, 'jobs': None},
                  {'total_count': True, 'jobs': [good]}, {'total_count': -1, 'jobs': []},
                  {'total_count': 0, 'jobs': [good]}, {'total_count': 1, 'jobs': {}},
                  {'total_count': 2, 'jobs': [good]}, {'total_count': 1, 'jobs': [None]},
                  {'total_count': 1, 'jobs': [{'name': 'ci-required'}]},
                  {'total_count': 1, 'jobs': [{'conclusion': 'success'}]}]
        for value in values:
            with self.subTest(value=value):
                actions = cut.Actions(Mock())
                actions.find = Mock(return_value=run)
                actions.api = Mock(side_effect=[run, value])
                with self.assertRaises(cut.CutError):
                    actions.wait('ci.yml', 'main', 'A', 'push')
                actions.repo.run.assert_not_called()

    def test_final_run_state_malformed_cannot_authorize(self):
        run = dict(id=1, head_sha='A', head_branch='main', event='push',
                   status='completed', conclusion='success', html_url='url/1')
        for value in (None, {}, {**run, 'head_sha': None}, {**run, 'conclusion': True}):
            with self.subTest(value=value):
                actions = cut.Actions(Mock())
                actions.find = Mock(return_value=run)
                actions.api = Mock(return_value=value)
                with self.assertRaisesRegex(cut.CutError, 'workflow run schema'):
                    actions.wait('ci.yml', 'main', 'A', 'push')
                actions.api.assert_called_once_with('actions/runs/1')


@patch.dict('os.environ', ENV)
class RoundThreeTests(LeaseTestCase):
    make_repo = GitReplayTests.make_repo

    def attach_remote(self, root, repo):
        remote = cut.Repository(root / 'remote.git')
        remote.root.mkdir()
        remote.git('init', '--bare', '-q')
        repo.git('remote', 'add', 'origin', str(remote.root))
        repo.git('push', '-q', 'origin', 'HEAD:refs/heads/main')
        return remote

    def generators(self, repo):
        repo.python = Mock(side_effect=lambda *args: json.dumps({'0.3.27': 'old', '0.3.28': 'new'})
                           if '--print-digests' in args else '')

    def test_both_cleanup_entries_preserve_raced_tip_with_original_recorded_lease(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'local').mkdir()
            repo = self.make_repo(root / 'local')
            base = repo.git('rev-parse', 'HEAD')
            remote = self.attach_remote(root, repo)
            self.generators(repo)
            repo.checks = Mock()
            branch = 'release-cut/dry-run/123-2'
            ref = f'refs/heads/{branch}'
            original = repo.git
            prep = replacement = None
            def race(*args):
                nonlocal prep, replacement
                if args[0] == 'push' and args[-1].endswith(':' + ref):
                    prep = args[-1].split(':')[0]
                    # The lease exists before the push, even if its acknowledgement is lost.
                    self.assertEqual(cut.dry_run_lease_path(branch).read_text().strip(), prep)
                    original(*args)
                    original('commit', '--allow-empty', '-qm', 'another writer')
                    replacement = original('rev-parse', 'HEAD')
                    original('push', '-q', 'origin', f'{replacement}:{ref}')
                    raise cut.CutError('lost push acknowledgement')
                return original(*args)
            with patch.dict('os.environ', {'GITHUB_SHA': base}), patch.object(repo, 'git', side_effect=race), \
                    patch.object(cut, 'Actions'), self.assertRaisesRegex(cut.CutError, 'lease mismatch.*retained'):
                cut.orchestrate(repo, '', True)
            with patch.object(cut, 'Repository', return_value=repo):
                self.assertEqual(cut.main(['cleanup', '--branch', branch]), 1)
            self.assertEqual(remote.git('rev-parse', ref), replacement)
            self.assertEqual(cut.dry_run_lease_path(branch).read_text().strip(), prep)

    def test_cli_cleanup_without_recorded_lease_performs_no_git_operations(self):
        repo = Mock()
        with patch.object(cut, 'Repository', return_value=repo):
            self.assertEqual(cut.main(['cleanup', '--branch', 'release-cut/dry-run/123-2']), 0)
        repo.git.assert_not_called()

    def historical_collision(self, position):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'local').mkdir()
            repo = self.make_repo(root / 'local')
            base = repo.git('rev-parse', 'HEAD')
            self.generators(repo)
            title = 'Release cut: prepare 0.3.28'
            if position in {'before', 'only'}:
                repo.git('commit', '--allow-empty', '-qm', title)
            prep = None
            if position != 'only':
                repo.prepare_files('0.3.28', '2026-10-17')
                prep = repo.commit('prepare', '0.3.28', '2026-10-17')
            if position == 'after':
                repo.git('commit', '--allow-empty', '-qm', title)
            main = repo.git('rev-parse', 'HEAD')
            self.attach_remote(root, repo)
            repo.checks = Mock()
            with patch.dict('os.environ', {'GITHUB_SHA': base}), patch.object(cut, 'Actions') as actions, \
                    patch.object(repo, 'git', wraps=repo.git) as git:
                actions.return_value.wait.side_effect = cut.CutError('stop at CI')
                reason = 'main_advanced_after_promotion' if position == 'after' else 'stop at CI'
                with self.assertRaisesRegex(cut.CutError, reason):
                    cut.orchestrate(repo, '', False)
                pushes = [c.args for c in git.call_args_list if c.args[0] == 'push']
                if position == 'only':
                    new_prep = repo.git('rev-parse', 'HEAD')
                    self.assertEqual(repo.git('rev-parse', new_prep + '^'), main)
                    self.assertEqual(pushes, [('push', 'origin',
                        f'{new_prep}:refs/heads/release-cut/v0.3.28/prepare')])
                    actions.return_value.wait.assert_called_once_with('ci.yml',
                        'release-cut/v0.3.28/prepare', new_prep, 'push')
                else:
                    self.assertEqual(pushes, [])
                    if position == 'before':
                        actions.return_value.wait.assert_called_once_with('ci.yml', 'main', prep, 'push')
                    else:
                        actions.return_value.wait.assert_not_called()

    def test_ordinary_same_title_before_real_prep(self):
        self.historical_collision('before')

    def test_ordinary_same_title_after_real_prep(self):
        self.historical_collision('after')

    def test_ordinary_same_title_without_real_prep_allows_prepare(self):
        self.historical_collision('only')

    def test_rejected_candidate_leaves_trusted_base_for_following_step(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = self.make_repo(directory)
            repo.write('scripts/following.py', 'print("trusted")\n')
            repo.git('add', '.')
            repo.git('commit', '-qm', 'trusted following step')
            base = repo.git('rev-parse', 'HEAD')
            self.generators(repo)
            repo.prepare_files('0.3.28', '2026-10-17')
            prep = repo.commit('prepare', '0.3.28', '2026-10-17')
            repo.validate_candidate(prep, 'prepare', '0.3.28', base)
            self.assertEqual(repo.git('rev-parse', 'HEAD'), prep)
            repo.write('scripts/following.py', 'raise RuntimeError("rejected code")\n')
            repo.git('add', '.')
            repo.git('commit', '--amend', '--no-edit', '-q')
            rejected = repo.git('rev-parse', 'HEAD')
            with self.assertRaisesRegex(cut.CutError, 'tree differs'):
                repo.validate_candidate(rejected, 'prepare', '0.3.28', base)
            self.assertEqual(repo.git('rev-parse', 'HEAD'), base)
            self.assertEqual(repo.git('status', '--porcelain'), '')
            self.assertEqual(cut.Repository.python(repo, 'scripts/following.py'), 'trusted')

    def test_bot_titled_non_candidates_do_not_block_legitimate_prepare(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'local').mkdir()
            repo = self.make_repo(root / 'local')
            base = repo.git('rev-parse', 'HEAD')
            for stamp in ('', '2026-02-30', '2026-10-17'):
                repo.git('-c', 'user.name=github-actions[bot]', '-c',
                         'user.email=41898282+github-actions[bot]@users.noreply.github.com',
                         'commit', '--allow-empty', '-qm', 'Release cut: prepare 0.3.28',
                         '-m', f'Release-Cut-Date: {stamp}')
            main = repo.git('rev-parse', 'HEAD')
            self.attach_remote(root, repo)
            self.generators(repo)
            repo.checks = Mock()
            with patch.dict('os.environ', {'GITHUB_SHA': base}), patch.object(cut, 'Actions') as actions:
                actions.return_value.wait.side_effect = cut.CutError('fresh prep reached CI')
                with self.assertRaisesRegex(cut.CutError, 'fresh prep reached CI'):
                    cut.orchestrate(repo, '', False)
            self.assertEqual(repo.git('rev-parse', 'HEAD^'), main)
            self.assertIn('## [0.3.28] - ', repo.read('CHANGELOG.md'))
