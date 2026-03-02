import logging

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)

from .const import (
    CONF_DATABASE,
    CONF_IMPORT_HISTORY,
    CONF_PASSWORD,
    CONF_USERNAME,
    DOMAIN,
)
from .coordinator import async_validate_credentials

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_DATABASE): str,
    }
)


class EcoguardOptionsFlow(OptionsFlow):
    async def async_step_init(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_IMPORT_HISTORY,
                        default=self.config_entry.options.get(
                            CONF_IMPORT_HISTORY, True
                        ),
                    ): bool,
                }
            ),
        )


class EcoguardConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry):
        return EcoguardOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                await async_validate_credentials(
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                    user_input[CONF_DATABASE],
                )
            except Exception:
                _LOGGER.exception("Failed to validate credentials")
                errors["base"] = "invalid_auth"
            else:
                await self.async_set_unique_id(
                    f"{user_input[CONF_DATABASE]}_{user_input[CONF_USERNAME]}"
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Ecoguard {user_input[CONF_USERNAME]}",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
