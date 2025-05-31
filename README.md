## To Do
Prompt..
Den funkade första gången, men om jag kör ett par "Preview" och "Assemble" så funkar den inte, den ska ersätta "Render Layers" om det finns en.
Kanske tom en input ruta där man kan fritexta vilken nod den skall använda, och en checkbox som för att aktivera. Typ "Overwrite Render Layer Name of Node:"


Kolla varför det står:
"Rendering preview assembly..."
"Rendering EXR assembly..."
Den renderar inte va?

Strukturera upp panelen (UI) så det är mer logiskt.

Den skall skicka tillbaks results till render-view medans den renderar, typ varje 25%. För snabb feedback. Det är det som är hela grejen.
  

# USP  
- Bucket rendering, skicka tillbaks live feedback när en bucket är klar i render-view. Som Team Render gör.
- Snabb feedback på sina ändringar, se direkt i render-view. Kommer spara kreativiteten. Kanske göra render-region, men behålla det andra synligt.
- High resolution rendering, test-rendera i ex HD lokalt med rendera i 16K hos Azure.
- Skicka iväg på rendering och jobba vidare med andra saker.