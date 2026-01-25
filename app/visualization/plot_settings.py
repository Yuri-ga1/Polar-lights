import matplotlib.pyplot as plt

# --- Константы ---
POINT_RADIUS = 2

# --- Глобальные параметры графиков ---
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
    plt.style.use('seaborn-v0_8-whitegrid')
    PLOTTING_PARAMS = {
        'font.size': 30,
        'figure.dpi': DPI,
        #'font.family': 'serif',
        #'font.family': 'monospace',
        #'font.style': 'normal',
        'font.weight': 'light',
        'legend.frameon': True,
        'font.variant' : 'small-caps',
        'axes.titlesize' : 30,
        'axes.labelsize' : 30,
        'xtick.labelsize' : 28,
        'ytick.labelsize' : 28,
        'xtick.major.pad': 5,
        'ytick.major.pad': 5,
        'xtick.major.width' : 2.5,
        'ytick.major.width' : 2.5,
        'xtick.minor.width' : 2.5,
        'ytick.minor.width' : 2.5,
    }
    plt.rcParams.update(PLOTTING_PARAMS)
