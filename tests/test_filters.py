from beatcut.grades import GRADES, grade_filter
from beatcut.plan import Plan
from beatcut.render import motion_filter, output_size, shot_filters


def plan(**kw):
    s = [{"src": "a.mp4", "start": 0, "duration": 1, "transition": "flash"},
         {"src": "b.mp4", "start": 0, "duration": 1, "transition": "flash"}]
    return Plan.from_dict({"size": [640, 360], "shots": s, **kw})


def test_flash_out_only_before_a_cut_and_in_after_it():
    p = plan()
    first, last = shot_filters(p, 0, (640, 360)), shot_filters(p, 1, (640, 360))
    assert "fade=t=out:s=27:n=3:color=white" in first and "fade=t=in" not in first
    assert "fade=t=in:s=0:n=5:color=white" in last
    assert "fade=t=out" not in last  # the last shot has no next shot to flash into


def test_crop_and_fit():
    p = Plan.from_dict({"size": [640, 360], "shots": [
        {"src": "a", "start": 0, "duration": 1, "crop": {"size": 0.5, "x": 0.25, "y": 0.1}}]})
    f = shot_filters(p, 0, (640, 360))
    assert "crop=trunc(iw*0.5/2)*2:trunc(ih*0.5/2)*2:iw*0.25:ih*0.1" in f
    assert "crop=640:360" in f and "tpad=stop_mode=clone:stop=30" in f


def test_shot_grade_overrides_plan_grade():
    p = Plan.from_dict({"grade": "dark", "shots": [
        {"src": "a", "start": 0, "duration": 1, "grade": "mono"}]})
    f = shot_filters(p, 0, (1920, 1080))
    assert GRADES["mono"] in f and GRADES["dark"] not in f


def test_motion_filters():
    assert motion_filter("none", 30, 30, (640, 360)) == ""
    assert "1+0.08*on/29" in motion_filter("push", 30, 30, (640, 360))
    assert "on/11" in motion_filter("punch", 30, 30, (640, 360))   # 0.35 s at 30 fps
    assert "s=640x360" in motion_filter("pull", 30, 30, (640, 360))


def test_preview_size_is_even():
    one = [{"src": "a", "start": 0, "duration": 1}]
    assert output_size(Plan.from_dict({"size": [1920, 1080], "shots": one}), True) == (640, 360)
    w, h = output_size(Plan.from_dict({"size": [2160, 3840], "shots": one}), True)
    assert w % 2 == 0 and h % 2 == 0


def test_grade_lookup():
    assert grade_filter("none") == ""
    assert grade_filter("custom:hue=s=0") == "hue=s=0"
