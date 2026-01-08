from enum import Enum

class AuroraColor(Enum):
    GREEN = "Green"
    RED = "Red"
    PURPLE = "Purple"
    BLUE = "Blue"

def get_dominant_color(color_str: str) -> str:
    """
    Определяет доминирующий цвет северного сияния
    по физическому приоритету (снизу вверх).

    Parameters
    ----------
    color_str : str
        Строка цветов, разделённых ; или пробелом, например:
        "Green;Red;Purple"

    Returns
    -------
    str
        Доминирующий цвет для точки
    """
    if not color_str:
        return "Unknown"

    # Разделяем цвета на список
    colors = [c.strip() for c in color_str.replace(";", " ").split() if c.strip()]

    priority = [
        AuroraColor.GREEN.value,
        AuroraColor.RED.value,
        AuroraColor.PURPLE.value,
        AuroraColor.BLUE.value
    ]


    for p in priority:
        if p in colors:
            return p

    return colors[0]