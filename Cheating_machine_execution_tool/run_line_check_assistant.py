import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()

    import argparse
    import os
    parser = argparse.ArgumentParser(description="LineCheckAssistant")
    parser.add_argument("--gateway-slot", type=int, help="显式启用已配对并在本地允许的统一接入槽位1至64")
    args = parser.parse_args()
    if args.gateway_slot is not None:
        if not 1 <= args.gateway_slot <= 64:
            parser.error("统一接入槽位须为1至64")
        os.environ["LINECHECK_GATEWAY_SLOT"] = str(args.gateway_slot)

    from line_check_assistant.app import main

    main()
