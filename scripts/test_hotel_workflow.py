from pathlib import Path
import unittest

WORKFLOW = Path(__file__).resolve().parents[1]/'.github/workflows/hotel-monitor.yml'


class WorkflowSafetyTests(unittest.TestCase):
    def test_checkout_is_trigger_commit_and_verified(self):
        text = WORKFLOW.read_text(encoding='utf-8')
        self.assertIn('ref: ${{ github.sha }}', text)
        self.assertNotIn('ref: master', text)
        self.assertIn('test "$(git rev-parse HEAD)" = "$EXPECTED_SHA"', text)

    def test_non_master_never_reaches_persistence_push(self):
        text = WORKFLOW.read_text(encoding='utf-8')
        save = text.split('- name: Save monitoring records', 1)[1].split('- name: Retain', 1)[0]
        self.assertIn("github.ref == 'refs/heads/master'", save)
        self.assertIn('if [ "$GITHUB_REF" != "refs/heads/master" ]; then exit 0; fi', save)
        self.assertLess(save.index('"$GITHUB_REF"'), save.index('git add'))
        self.assertIn("steps.query.outcome == 'success' || steps.query.outcome == 'failure'", save)
        self.assertIn("persist-credentials: ${{ github.ref == 'refs/heads/master' }}", text)

    def test_schedule_and_artifact_are_retained(self):
        text = WORKFLOW.read_text(encoding='utf-8')
        artifact = text.split('- name: Retain', 1)[1]
        self.assertIn('if: always()', artifact)
        self.assertIn('actions/upload-artifact@v4', artifact)
        self.assertIn('schedule:', text)
        self.assertIn('50 1 * * *', text)
        self.assertIn('airport-candidate', text)
        self.assertIn('marunouchi-booked', text)

    def test_unified_manual_request_cannot_update_monitor_config(self):
        text = WORKFLOW.read_text(encoding='utf-8')
        self.assertIn('request_json:', text)
        self.assertIn('run-request --request-file hotel-request.json', text)
        self.assertNotIn('--allow-monitor-update', text)
        self.assertIn('hotel-request-result.json', text)


if __name__ == '__main__': unittest.main()

