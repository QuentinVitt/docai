# Config Registry

Running notes on everything that should be configurable.
Add entries here as components are built — before the config system is implemented.

---

_(empty — fill in as components are built)_

# LLM

profiles:
  default: 
    model: gemini/gemini-2.5-flash # only one that needs to be set
    # api_key 
    # custom
    # temprature
    # top_p
    # n 
    # max_completion_tokens
    # max_tokens
    # presense_penalty
    # frequency_penalty
    # timeout
    # num_retries # this are connection retries not validation retries.
    # All that are not listed here can also be specified and are passed as kwargs to the provider interface
    # docai specific
  flash: 
    ...

profile_default: 
    # set any standart settings for an llm config. If now specified in the profile this is selected. 
    
globals:
    # max_concurrent_request
    # validation_retries
