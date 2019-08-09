PLUGIN_NAME = __package__


def msg(message: str) -> str:
    """
    @brief Generate plugin message.

    @param message The message

    @return The plugin message.
    """

    return "[{plugin}] {message}".format(plugin=PLUGIN_NAME, message=message)


def print_msg(message, show_message=True):
    if show_message:
        print(msg(message))
