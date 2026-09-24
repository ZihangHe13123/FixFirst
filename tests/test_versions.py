from packaging.version import Version

from fixfirst import versions

MAC = {"platform_system": "Darwin", "platform_machine": "arm64"}


def pypi(*releases, wheel="demo-{v}-py3-none-any.whl"):
    return {"releases": {v: [{"packagetype": "bdist_wheel", "filename": wheel.format(v=v)}] for v in releases}}


class FakeSandbox:
    """Releases up to `last` provide the name; releases in `broken` do not install."""

    def __init__(self, last, broken=()):
        self.last, self.broken, self.tried = Version(last), set(broken), []

    def __call__(self, python):
        return self

    def provides(self, dist, version, module, name):
        self.tried.append(version)
        if version in self.broken:
            return "failed"
        return "provides" if Version(version) <= self.last else "missing"

    def close(self):
        pass


def run(data, box, installed="1.9.1"):
    return versions.search("python", "3.12.4", MAC, "demo", installed, "demo.utils.helper",
                           fetch=lambda url: data, sandbox=box)


def test_wheel_tags_decide_which_releases_can_be_tried():
    python = Version("3.12.4")
    assert versions.wheel_fits("pkg-1.0-py3-none-any.whl", python, MAC)
    assert versions.wheel_fits("pkg-1.0-cp312-cp312-macosx_11_0_arm64.whl", python, MAC)
    assert versions.wheel_fits("pkg-1.0-cp38-abi3-macosx_10_9_universal2.whl", python, MAC)
    assert not versions.wheel_fits("pkg-1.0-cp311-cp311-macosx_11_0_arm64.whl", python, MAC)
    assert not versions.wheel_fits("pkg-1.0-cp312-cp312-win_amd64.whl", python, MAC)


def test_only_the_newest_release_of_each_older_series_is_a_candidate():
    data = pypi("1.3.0", "1.3.2", "1.4.0", "1.4.2", "1.9.0", "1.9.1", "2.0rc1")
    data["releases"]["1.2.0"] = [{"packagetype": "sdist", "filename": "demo-1.2.0.tar.gz"}]
    assert versions.candidates(data, "1.9.1", "3.12.4", MAC) == ["1.4.2", "1.3.2"]


def test_search_finds_the_newest_series_that_still_has_the_name():
    data = pypi(*[f"1.{m}.{p}" for m in range(0, 10) for p in (0, 1)])
    box = FakeSandbox(last="1.4.1")
    result = run(data, box)
    assert (result["status"], result["provides"], result["below"]) == ("found", "1.4.1", "1.5")
    assert len(box.tried) <= 6  # 1.8, 1.7, 1.5, 1.1 by doubling steps, then bisection


def test_search_skips_releases_that_cannot_be_judged():
    data = pypi(*[f"1.{m}.0" for m in range(0, 10)])
    result = run(data, FakeSandbox(last="1.4.0", broken={"1.7.0", "1.5.0"}))
    # 1.5 could not be judged, so the bound stops right after the verified 1.4.
    assert (result["status"], result["provides"], result["below"], result["first_without"]) == (
        "found", "1.4.0", "1.5", "1.6"
    )


def test_search_reports_when_no_older_release_has_the_name():
    data = pypi("1.0.0", "1.1.0", "1.2.0")
    result = run(data, FakeSandbox(last="0.1"), installed="1.3.0")
    assert result["status"] == "not_found" and result["provides"] is None


def test_search_without_network_says_so():
    def offline(url):
        raise OSError("no network")

    result = versions.search("python", "3.12.4", MAC, "demo", "1.0", "demo.x", fetch=offline, sandbox=FakeSandbox("0"))
    assert result["status"] == "offline"
