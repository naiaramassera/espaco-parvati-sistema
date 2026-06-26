let currentStep = 0;

const steps = document.querySelectorAll(".step");
const progress = document.getElementById("progress");

function showStep(index){

steps.forEach((step,i)=>{
step.classList.remove("active");

if(i===index){
step.classList.add("active");
}

});

progress.style.width = ((index+1)/steps.length)*100+"%";
}

function nextStep(){

if(currentStep < steps.length-1){
currentStep++;
showStep(currentStep);
}

}

function prevStep(){

if(currentStep > 0){
currentStep--;
showStep(currentStep);
}

}

showStep(currentStep);