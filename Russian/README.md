# DDON-Rus
Русификатор Dragons Dogma Online
Гугл-перевод [английского перевода](https://github.com/Sapphiratelaemara/DDON-translation) с некоторыми ручными правками.
Файл `gmd.csv` содержит сам перевод на русский язык.
Файлы `gui_cmn.arc` и `gui_cmn_win.arc` содержат исправленный шрифт кириллицы в игре.

## Установка
1. Скачать [здесь](https://github.com/sebastian-heinz/Arrowgene.DragonsDogmaOnline/releases) архив с файлами сервера подходящий к вашей ОС.
2. Распаковать скачанный архив в любое место и разархивировать распакованный архив в любое место. В результате должна быть папка `./publish`.
3. Из папки `.\publish\win-x64-1.0.0.0` копируем папку `Server` и файл `pack_gmd_english.cmd` в папку `nativePC` в папке с игрой, а именно в `Dragons Dogma Online\nativePC` приняв замену файлов.
4. Файл `gmd.csv` скачанный из этого репозитория поместить в папку `Dragons Dogma Online\nativePC\Server\Files\Client` приняв замену.
5. Запустить процесс перевода игровых файлов - перейти в папку `Dragons Dogma Online\nativePC` и перетянуть папку `rom` на файл `pack_gmd_english.cmd`. Должно открыться окно с командной строкой отображающее прогресс процесса перевода.
6. По окончанию процесса перевода файлы `gui_cmn.arc` и `gui_cmn_win.arc` скачанные из этого репозитория скопировать в папку `Dragons Dogma Online\nativePC\rom\ui` приняв замену.
7. Установить `.NET SDK 10.0.0`.

## Исправления
Возможно, что у Вас возникнут ошибки при установке, для того, чтобы минимизировать вероятность их появления:

Откройте папку `Диск:\Dragons Dogma Online\nativePC\Server\` и проверьте, есть ли там файл `Arrowgene.Ddon.Cli.dll` (рядом с `.exe`).

Нажмите правой кнопкой мыши по файлу `pack_gmd_english.cmd` в папке `nativePC` и выберите `Изменить`.

Замените строку вызова утилиты (самую длинную) так, чтобы она начиналась со слова `dotnet` и обращалась к `.dll` файлу.

Пример того, как должна выглядеть эта строка в скрипте:
dotnet "%~dp0Server\Arrowgene.Ddon.Cli.dll" client packGmd romDir="%1" gmdCsv="%~dp0Server\Files\Client\gmd.csv" romLang="English"

Пример готового кода:
set DOTNET_ROOT=C:\Program Files\dotnet
pushd "%~dp0"
cd ./Server
dotnet Arrowgene.Ddon.Cli.dll client packGmd romDir="%~dp0rom" gmdCsv="%~dp0Server\Files\Client\gmd.csv" romLang="English"
pause
