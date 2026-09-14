import threading


class CosyVoiceFlowStepController:
    """
    Runtime controller for CosyVoice Flow inference steps.

    Allows Sara to switch Flow steps between requests without
    modifying CosyVoice source files or rebuilding TensorRT.

    Intended test values:
        10 = original baseline
         8
         6
         5
    """

    ALLOWED_STEPS = {5, 6, 8, 10}

    def __init__(self, default_steps=10):
        self._lock = threading.Lock()

        self.default_steps = default_steps
        self.current_steps = default_steps

        self.original_forward = None
        self.installed = False


    def install(self, flow_decoder):
        """
        Wrap flow.decoder.forward() and replace the hardcoded
        n_timesteps value supplied by CosyVoice.
        """

        if self.installed:
            return

        self.original_forward = flow_decoder.forward

        controller = self

        def controlled_forward(*args, **kwargs):

            with controller._lock:
                steps = controller.current_steps

            # CosyVoice passes n_timesteps as a keyword:
            #
            # self.decoder(
            #     ...
            #     n_timesteps=10,
            #     streaming=streaming
            # )
            #
            # Replace that value at runtime.

            if "n_timesteps" in kwargs:
                kwargs["n_timesteps"] = steps

            return controller.original_forward(
                *args,
                **kwargs,
            )

        flow_decoder.forward = controlled_forward

        self.installed = True


    def set_steps(self, steps):
        """
        Set Flow inference steps for the next/current serialized
        TTS request.
        """

        try:
            steps = int(steps)

        except (TypeError, ValueError):
            steps = self.default_steps

        if steps not in self.ALLOWED_STEPS:
            steps = self.default_steps

        with self._lock:
            self.current_steps = steps

        return steps


    def reset(self):

        with self._lock:
            self.current_steps = self.default_steps

        return self.default_steps


    def get_steps(self):

        with self._lock:
            return self.current_steps
