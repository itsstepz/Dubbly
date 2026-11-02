import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()  # нужно для собранного .exe: дочерний процесс перевода
    from vt.gui import main

    main()
