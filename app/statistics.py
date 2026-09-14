"""
ConAI Statistics Engine
"""


class Statistics:

    def __init__(self):

        self.session_prompts = 0
        self.commands_used = 0

        self.total_inference_time = 0.0

        self.fastest_response = float("inf")
        self.slowest_response = 0.0

        self.total_context_messages = 0

    def record_chat(self, inference_time, context_size):

        self.session_prompts += 1

        self.total_inference_time += inference_time

        self.total_context_messages += context_size

        if inference_time < self.fastest_response:
            self.fastest_response = inference_time

        if inference_time > self.slowest_response:
            self.slowest_response = inference_time

    def record_command(self):

        self.commands_used += 1

    def average_inference(self):

        if self.session_prompts == 0:
            return 0

        return self.total_inference_time / self.session_prompts

    def average_context(self):

        if self.session_prompts == 0:
            return 0

        return self.total_context_messages / self.session_prompts

    def report(self):

        return f"""
========== ConAI Statistics ==========

Prompts              : {self.session_prompts}

Commands             : {self.commands_used}

Average Inference    : {self.average_inference():.2f} sec

Fastest Response     : {self.fastest_response:.2f} sec

Slowest Response     : {self.slowest_response:.2f} sec

Average Context      : {self.average_context():.1f} messages

======================================
"""