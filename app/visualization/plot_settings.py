import matplotlib.pyplot as plt

DPI = 300
FONT_SIZE = 16
TITLE_FONT_SIZE = 18
LEGEND_SIZE = 14
AXES_LABEL_SIZE = 12
TICKS_LABEL_SIZE = 12

def set_plt_def_params():
    """
    Устанавливает глобальные параметры matplotlib
    для всех графиков проекта.
    """
    plt.rcParams['figure.dpi'] = DPI
    plt.rcParams['savefig.dpi'] = DPI
    plt.rcParams['font.size'] = FONT_SIZE
    plt.rcParams['axes.titlesize'] = TITLE_FONT_SIZE
    plt.rcParams['axes.labelsize'] = AXES_LABEL_SIZE
    plt.rcParams['xtick.labelsize'] = TICKS_LABEL_SIZE
    plt.rcParams['ytick.labelsize'] = TICKS_LABEL_SIZE - 1
    plt.rcParams['legend.fontsize'] = LEGEND_SIZE
