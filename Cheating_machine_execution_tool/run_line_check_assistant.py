import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()

    from line_check_assistant.app import main

    main()
