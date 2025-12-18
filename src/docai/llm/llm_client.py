import asyncio
import logging
import os
from importlib import resources

import yaml
from google import genai
from google.genai import types

logger = logging.getLogger("docai_project")

CONFIG_PACKAGE = "docai.config"
CONFIG_FILE = "llm_config.yaml"


### call_llm function:
# input:
# - contents: prompt (str) and history
# - system_prompt: str, optional
# - structured_output:
# output:
#
# function_call: bool,
# response: str, or function_call.name: str, and function_call.arguments: dict


class llm_client:
    def __init__(
        self,
        model: str | None = None,
        usecase: str | None = None,
        agent_mode: bool = False,
    ):
        logger.debug("Initializing llm_client")
        logger.debug("Loading llm config file")
        # load config file
        try:
            config_test = resources.open_text(CONFIG_PACKAGE, CONFIG_FILE)
        except FileNotFoundError:
            logger.fatal("Logging configuration file not found")
            exit(1)

        config = yaml.safe_load(config_test)

        # get the model
        if model:
            logger.debug("Getting model from arguments")
        elif usecase:
            logger.debug("Getting default model for usecase %s", usecase)
            model = self.__get_model_from_usecase(usecase, config)
        else:
            logger.debug("Getting default model")
            model = self.__get_default_model(config)

        # get the provider
        logger.debug("Getting provider for model %s", model)
        provider = self.__get_provider_from_model(model, config)

        if provider is None:
            logger.critical("No provider found for model %s", model)
            exit(1)

        logger.debug("Provider found: %s", provider)

        # configure the provider
        logger.debug("Configure provider and set-up wrapper function for call_llm")
        match provider:
            case "google":
                self.call_llm = self.__configure_google_llm(model, config, agent_mode)
            case _:
                logger.critical("Unsupported provider: %s", provider)
                exit(1)

    def __get_model_from_usecase(self, usecase: str, config: dict) -> str:
        try:
            return config["usecases"][usecase]["model"]
        except KeyError:
            logger.critical(
                "Usecase %s not found in configuration", usecase, exc_info=True
            )
            exit(1)
        except Exception:
            logger.critical(
                "Unexpected error while getting model from usecase: %s",
                usecase,
                exc_info=True,
            )
            exit(1)

    def __get_default_model(self, config: dict) -> str:
        try:
            return config["usecases"]["default"]["model"]
        except KeyError:
            logger.critical("Default model not found in configuration", exc_info=True)
            exit(1)
        except Exception:
            logger.critical(
                "Unexpected error while getting default model", exc_info=True
            )
            exit(1)

    def __get_provider_from_model(self, model: str, config: dict) -> str:
        logger.debug("Getting provider from model %s", model)
        try:
            return config["models"][model]["provider"]
        except KeyError:
            logger.critical("Model %s not found in configuration", model, exc_info=True)
            exit(1)
        except Exception:
            logger.critical(
                "Unexpected error while getting provider from model", exc_info=True
            )
            exit(1)

    def __configure_google_llm(
        self, model: str, config: dict, agent_mode: bool = False
    ):
        # check if API key is set
        logger.debug("Checking if an API key is set")
        api_key_name = config["providers"]["google"]["api_key_env"]
        api_key = os.environ.get(api_key_name)
        if not api_key:
            logger.critical("API key %s not set", api_key_name)
            exit(1)

        client = genai.Client(api_key=api_key)
        logger.debug("New google client created")
        model_config = config["models"][model]
        generation_config = model_config.get("generation", {})

        if agent_mode:
            logger.critical("Agent mode is not implemented")
            exit(1)

        async def wrapper(
            contents: str,
            system_prompt: str | None = None,
            structured_output: dict | None = None,
        ):
            # Keep wrapper async; offload sync SDK call to a thread
            if system_prompt:
                generation_config["system_prompt"] = system_prompt
            if structured_output:
                logger.critical("Structured output is implemented")
                exit(1)

            def _call():
                return client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=types.GenerateContentConfig(**generation_config),
                )

            try:
                response = await asyncio.to_thread(_call)
            except Exception as e:
                logger.exception("Google LLM call failed: \n%s", e, exc_info=True)
                raise

            return False, response.text

        return wrapper
