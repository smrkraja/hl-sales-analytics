"""City -> landmark photo for the sign-in banner.

To add a city: put a wide image in app/static/landmarks/, record its source and
license in the README there, and add an entry keyed by the lower-case city name.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Landmark:
    name: str
    image: str            # path under app/static/
    focus: str = "center"  # CSS background-position, to keep the landmark in frame


LANDMARKS = {
    "san francisco": Landmark(
        name="Golden Gate Bridge",
        image="landmarks/san-francisco.jpg",
        focus="center 55%",
    ),
}


def city_of(location: str | None) -> str | None:
    """'San Francisco, CA, US' -> 'san francisco'."""
    if not location:
        return None
    city = location.split(",")[0].strip().lower()
    return city or None


def landmark_for(location: str | None) -> Landmark | None:
    return LANDMARKS.get(city_of(location))
