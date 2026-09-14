# TODO — Fix the interactive steering loop

## Problem

The interactive mode effectively does not work: after the user submits a guidance
prompt, healing never happens:

1. the regenerated code fails with runtime errors;
2. the LLM appears not to see that the page has changed;
3. the generated code is never shown, so there is no way to tell what went wrong
   with the LLM.

## Reproduction scenario

- Open Google
- Enter a query
- Check the results

After submitting the query a CAPTCHA appears. The step fails with a correct
explanation and the interactive mode starts. The engineer solves the CAPTCHA
manually and tells the LLM so ("я прошел капчу"). The LLM still cannot recover
and heal the step even though the page state is already correct.

## Observed dialog (session log)

```
guidance> я прошел капчу
regenerating with USER GUIDANCE — executing against the live page
turn failed: name 're' is not defined

guidance> я прошел капчу
turn failed: value must be a string or regular expression

guidance> Попробуй еще раз
turn failed: Page URL expected to be '**/search**'
(actual URL already https://www.google.com/search?q=UI+testing+automation…)

guidance> Я уже ввел капчу, перезагрузи страницу и перегененрируй код шага
turn failed: Page.reload: Timeout 30000ms exceeded.

guidance> FAILED
```

## Additional problem

The snapshot embedded in the error output makes the error effectively unreadable
and adds no informative value.
