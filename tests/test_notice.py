import json
import unittest
from unittest.mock import Mock

from monitor.live import BalanceReader
from monitor.notice import find_defer_action, page_structure
from tests.test_live import response, sequence, session_responses


HEAD = "<h2>비밀번호 변경안내</h2><p>회원님께서는 장기간 비밀번호를 변경하지 않고 동일한 비밀번호를 사용하고 계십니다.</p>"
AJAX_PAGE = HEAD + """
<button id="btnChgPswd">비밀번호 변경</button><button id="btnNextChg" type="button">다음에 변경</button>
<script>
$("#btnChgPswd").click(function(){ location.href = "/mbrsrvc/chgPswd"; });
$("#btnNextChg").click(function(){
  ajaxUtil.sendHttpJson({}, "/login/updateNextPswdChg.do", {"method": "POST"}, function(){ location.href = "/main"; });
});
</script>"""
FORM_PAGE = HEAD + """
<form id="nextForm" method="post"><input type="hidden" name="nextYn" value="Y"><input type="hidden" name="token" value="abc123"></form>
<a href="#" onclick="fnNext(); return false;">다음에 변경</a>
<script>function fnNext(){ $("#nextForm").attr("action", "/login/pswdChgNext.do"); $("#nextForm").submit(); }</script>"""
LINK_PAGE = HEAD + '<a href="/main?pswdNext=Y">다음에 변경</a><a href="/mbrsrvc/chgPswd">비밀번호 변경</a>'


def login_with(page, *after):
    replies = sequence()
    replies[3] = response(text=page)
    return session_responses(*(replies[:4] + list(after)))


class NoticeTests(unittest.TestCase):
    def test_finds_ajax_link_and_form_actions(self):
        ajax = find_defer_action(AJAX_PAGE)
        self.assertEqual((ajax.method, ajax.path, ajax.kind), ("POST", "/login/updateNextPswdChg.do", "ajax"))
        form = find_defer_action(FORM_PAGE)
        self.assertEqual((form.method, form.path, form.kind, form.data), ("POST", "/login/pswdChgNext.do", "form", {"nextYn": "Y", "token": "abc123"}))
        link = find_defer_action(LINK_PAGE)
        self.assertEqual((link.method, link.path), ("GET", "/main?pswdNext=Y"))

    def test_never_guesses(self):
        for page in [HEAD, HEAD + "<button>다음에 변경</button><button>다음에 하기</button>",
                     HEAD + '<a href="https://evil.example/next">다음에 변경</a>',
                     HEAD + '<button id="x">다음에 변경</button><script>$("#x").click(function(){ alert(1); });</script>']:
            with self.subTest(page=page[-60:]):
                self.assertIsNone(find_defer_action(page))

    def test_structure_has_names_and_paths_but_no_values(self):
        structure = page_structure(FORM_PAGE)
        self.assertEqual(structure["forms"][0]["inputs"], ["nextYn", "token"])
        self.assertNotIn("abc123", json.dumps(structure))
        self.assertIn("다음에 변경", structure["buttons"])

    def test_login_presses_remind_later_then_verifies_balance(self):
        session = login_with(AJAX_PAGE, response({"resultCode": None}), response({"data": {"userMndp": {"totalAmt": 5000}}}))
        outcome = BalanceReader(session, Mock(return_value={})).read("example", "example")
        self.assertEqual((outcome.code, outcome.result.balance_krw), ("balance_verified", 5000))
        call = session.request.call_args_list[4]
        self.assertEqual((call.args[0], call.args[1]), ("POST", "https://www.dhlottery.co.kr/login/updateNextPswdChg.do"))
        self.assertEqual(call.kwargs["json"], {})
        self.assertEqual(json.loads(outcome.diagnostic())["notice_deferred"], "/login/updateNextPswdChg.do")

    def test_form_submit_sends_page_hidden_fields(self):
        session = login_with(FORM_PAGE, response(text="<html>main</html>"), response({"data": {"userMndp": {"totalAmt": 0}}}))
        outcome = BalanceReader(session, Mock(return_value={})).read("example", "example")
        self.assertEqual(outcome.code, "balance_verified")
        self.assertEqual(session.request.call_args_list[4].kwargs["data"], {"nextYn": "Y", "token": "abc123"})
        self.assertNotIn("abc123", outcome.diagnostic())

    def test_still_not_logged_in_after_press_is_reported(self):
        session = login_with(AJAX_PAGE, response({}), response(status=401))
        outcome = BalanceReader(session, Mock(return_value={})).read("example", "example")
        self.assertEqual(outcome.code, "password_notice_defer_failed")

    def test_unknown_notice_layout_stops_and_logs_structure(self):
        session = login_with(HEAD + '<button id="q">다음에 변경</button>')
        outcome = BalanceReader(session, Mock(return_value={})).read("example", "example")
        self.assertEqual(outcome.code, "password_change_notice")
        self.assertEqual(session.request.call_count, 4)
        self.assertEqual(json.loads(outcome.diagnostic())["notice"]["buttons"], ["다음에 변경"])


if __name__ == "__main__":
    unittest.main()
