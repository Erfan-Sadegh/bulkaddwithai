from app.basalam_categories import BasalamCategory, suggest_category


def test_suggest_category_keeps_confident_match_when_title_has_signal():
    categories = [
        BasalamCategory(id=1, title="سرگرمی", path="خانه و آشپزخانه > سرگرمی"),
        BasalamCategory(id=2, title="ساعت و مچ بند هوشمند", path="کالای دیجیتال > ساعت و مچ بند هوشمند"),
    ]

    suggested = suggest_category(categories, "ساعت هوشمند با بند صوتی", "محصول با رنگ صورتی")

    assert suggested is not None
    assert suggested.id == 2
    assert suggested.confidence is not None
    assert suggested.confidence >= 0.62


def test_suggest_category_caps_confidence_when_title_has_no_signal():
    categories = [
        BasalamCategory(id=1, title="سرگرمی", path="خانه و آشپزخانه > سرگرمی"),
        BasalamCategory(id=2, title="ساعت و مچ بند هوشمند", path="کالای دیجیتال > ساعت و مچ بند هوشمند"),
    ]

    suggested = suggest_category(categories, "محصول تستی", "برای سرگرمی و استفاده روزانه مناسب است")

    assert suggested is not None
    assert suggested.id == 1
    assert suggested.confidence is not None
    assert suggested.confidence < 0.62


def test_suggest_category_prefers_digital_audio_for_airpods():
    categories = [
        BasalamCategory(id=1, title="سرگرمی", path="خانه و آشپزخانه > سرگرمی"),
        BasalamCategory(id=2, title="هندزفری و هدفون", path="کالای دیجیتال > صوتی و تصویری > هندزفری و هدفون"),
        BasalamCategory(id=3, title="لوازم آشپزخانه", path="خانه و آشپزخانه > لوازم آشپزخانه"),
    ]

    suggested = suggest_category(categories, "ایرپاد بلوتوثی مدل Pro", "ایرپاد با کیس شارژ")

    assert suggested is not None
    assert suggested.id == 2
    assert suggested.confidence is not None
    assert suggested.confidence >= 0.62


def test_suggest_category_penalizes_unrelated_general_category_for_smart_watch():
    categories = [
        BasalamCategory(id=1, title="سرگرمی", path="خانه و آشپزخانه > سرگرمی"),
        BasalamCategory(id=2, title="ساعت و مچ بند هوشمند", path="کالای دیجیتال > ساعت و مچ بند هوشمند"),
    ]

    suggested = suggest_category(categories, "بند ساعت هوشمند صورتی", "مناسب اپل واچ")

    assert suggested is not None
    assert suggested.id == 2
    assert suggested.confidence is not None
    assert suggested.confidence >= 0.62
